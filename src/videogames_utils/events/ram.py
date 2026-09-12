"""Candidate RAM addresses for the CNeuroMod videogame integrations, and the harness
that verifies them before they are added to a dataset's ``stimuli/<Game>/data.json``.

Every address here is sourced from a public disassembly and must pass its checks in
``verify_addresses.py`` against an independent truth signal before it ships. Nothing in
this module writes to a dataset; the harness builds a throwaway *shadow* integration in
a temporary directory instead.

Sources
-------
SuperMarioBros-Nes
    1wErt3r's SMB disassembly (SMBDIS.ASM), https://gist.github.com/1wErt3r/4048722
SuperMarioBros3-Nes
    captainsouthbird's SMB3 disassembly (smb3.asm),
    https://github.com/captainsouthbird/smb3
SuperMarioAllStars-Snes
    Data Crystal's partial SMAS map plus addresses already present in the dataset's own
    data.json, https://datacrystal.tcrf.net/wiki/Super_Mario_All-Stars_(SNES)/RAM_map
"""

from __future__ import annotations

import json
import os
import os.path as op
import shutil
import tempfile
import warnings
from dataclasses import dataclass
from typing import Dict, List

import stable_retro as retro

from ..replay import get_variables_from_replay


# --------------------------------------------------------------------------- specs


@dataclass
class Candidate:
    """One RAM variable proposed for addition to an integration's ``data.json``.

    Attributes:
        name: Key to write into ``data.json`` (and hence into ``_variables.json``).
        address: Decimal address, as ``data.json`` expects.
        dtype: stable-retro type string, e.g. ``"|u1"``.
        symbol: The disassembly label this address corresponds to.
        note: Why we want it / what it decodes to.
    """

    name: str
    address: int
    dtype: str
    symbol: str
    note: str = ""

    def as_json_entry(self) -> dict:
        return {"address": self.address, "type": self.dtype}


def _array(prefix: str, base: int, count: int, dtype: str, symbol: str, note: str = ""):
    """Expand a contiguous RAM array into one Candidate per slot."""
    return [
        Candidate(f"{prefix}_{i}", base + i, dtype, f"{symbol}[{i}]", note)
        for i in range(count)
    ]


# --- Super Mario Bros (NES) -------------------------------------------------------
# Enemy object arrays are 6 slots wide. Enemy_ID[5] is already present in the shipped
# data.json under the (misleading) name "powerup_yes_no", Enemy_Flag[0..4] under
# "enemy_drawn15".."enemy_drawn19", and Enemy_State[0..5] under "enemy_kill30".."enemy_kill35".

SMB1_CANDIDATES: List[Candidate] = [
    *_array("enemy_id", 0x16, 6, "|u1", "Enemy_ID", "enemy type per slot"),
    Candidate("enemy_drawn20", 0x14, "|u1", "Enemy_Flag[5]", "6th Enemy_Flag slot"),
    *_array("enemy_x", 0x87, 6, "|u1", "Enemy_X_Position", "screen X per slot"),
    *_array("enemy_y", 0xCF, 6, "|u1", "Enemy_Y_Position", "screen Y per slot"),
    *_array("enemy_pageloc", 0x6E, 6, "|u1", "Enemy_PageLoc",
            "X page per slot; absolute X = pageloc * 256 + enemy_x"),
    *_array("enemy_y_high", 0xB6, 6, "|u1", "Enemy_Y_HighPos",
            "Y page per slot; 1 = within the visible band"),
    # Enemy_OffscreenBits ($03D1) is SCRATCH - it holds the bits of whichever enemy is
    # being processed on this frame, not a per-slot mask (verified empirically: slots 4
    # and 5 never set their bit). The persistent per-slot array is EnemyOffscrBitsMasked.
    *_array("enemy_offscr_masked", 0x03D8, 6, "|u1", "EnemyOffscrBitsMasked",
            "per-slot: non-zero = enemy is offscreen by some amount"),
    *_array("enemy_sprattrib", 0x03C5, 6, "|u1", "Enemy_SprAttrib",
            "per-slot sprite attributes"),
    # PlayerStatus is a single byte, but the shipped data.json declares this same address
    # as "powerstate" with type ">d4" -- a 4-byte BCD read spanning $0756-$0759, so it
    # mixes in the neighbouring death flag at $0757 and reports values like 10000. The
    # shipped generator never reads it, which is why the bug went unnoticed. "powerstate"
    # is left in place (removing it would break anyone reading it); use this instead.
    # Verified: reads 0/1/2 with clean transitions 0->1 on a mushroom, 1->2 on a fire
    # flower and 2->0 on taking damage.
    Candidate("player_status", 0x0756, "|u1", "PlayerStatus",
              "0 small, 1 super, 2 fire -- correctly typed replacement for 'powerstate'"),
    # InjuryTimer is the post-hit invulnerability window. ForceInjury sets it to 8 when a
    # big Mario is hit and InjurePlayer ignores enemy contact while it is non-zero; it
    # counts on the 21-frame interval clock and pauses while the shrink animation halts
    # the timers, so it runs ~220 frames (3.7 s). Verified: non-zero from exactly the
    # engine-10 frame for 223 frames in a w1-2 replay, 8 -> 1.
    Candidate("injury_timer", 0x079E, "|u1", "InjuryTimer",
              "post-hit invulnerability countdown, 8 -> 0 (interval-timer units)"),
    # NOTE: HalfwayPage is written when the player DIES past the level midpoint, to place
    # the respawn, not when the midpoint is crossed. Verified: in a w1-1 replay it is
    # non-zero only during the two death/respawn sequences. It therefore cannot mark
    # Checkpoint_reached; kept because it records whether a respawn used the checkpoint.
    Candidate("halfway_page", 0x075B, "|u1", "HalfwayPage",
              "respawn page, written at death past the midpoint (NOT a crossing marker)"),
    Candidate("event_music_queue", 0xFC, "|u1", "EventMusicQueue",
              "0x01 death, 0x20 end-of-level, 0x40 time-running-out"),
    Candidate("player_collision_bits", 0x0490, "|u1", "Player_CollisionBits", ""),
    Candidate("enemy_collision_bits", 0x0491, "|u1", "Enemy_CollisionBits", ""),
    Candidate("stomp_chain_counter", 0x0484, "|u1", "StompChainCounter", ""),
    Candidate("enemy_frenzy_buffer", 0x06CB, "|u1", "EnemyFrenzyBuffer",
              "frenzy spawner (Bullet Bill / Cheep-Cheep)"),
    Candidate("frenzy_enemy_timer", 0x078F, "|u1", "FrenzyEnemyTimer", ""),
    Candidate("area_type", 0x074E, "|u1", "AreaType",
              "0 water, 1 ground, 2 underground, 3 castle"),
]

# --- Super Mario All-Stars, SMB1 (SNES) --------------------------------------------
# The port keeps SMB1's $07xx player block at the same WRAM offsets ($7E0756 is still
# PlayerStatus) and shifts the timer block by +$10. The shipped data.json's
# "player_powerup" ($0578) and "star_power_timer" ($0553) do NOT hold what their names
# say: over all 1232 replays player_powerup takes values such as 28, 82, 107 and 231 with
# no relation to the engine's grow/hit transitions (it produced rows like
# "Powerup_started/107"), and star_power_timer holds constants rather than a countdown.
# Both are left in place (see apply_ram.MISLABELLED); the generator uses these instead.
#
# Found by recording the first 8 KB of WRAM on every frame of a w4-2 replay containing
# two mushrooms, two fire flowers and two hits, and keeping the bytes whose value is
# constant between the engine's 9/12/10 transitions and differs across them: exactly one
# byte qualifies. The two timers were then confirmed through the emulator's own
# variable reader (values 8 -> 1 over 212 frames after each hit; 35 -> 1 over 730 frames
# after a star in a w5-1 replay), i.e. the NES behaviour to the frame.
#
# Addresses are written the way the existing entries are: as offsets in the 8 KB block
# at 0 that the core exposes as a mirror of $7E0000-$7E1FFF.

SMAS_CANDIDATES: List[Candidate] = [
    Candidate("player_status", 0x0756, "|u1", "PlayerStatus",
              "0 small, 1 super, 2 fire; changes on the frame the engine enters 9/12 "
              "(grow / fire flower) or 10 (injury). Replaces 'player_powerup'"),
    Candidate("injury_timer", 0x07AE, "|u1", "InjuryTimer",
              "post-hit invulnerability countdown, 8 -> 0 over ~212 frames"),
    Candidate("star_timer", 0x07AF, "|u1", "StarInvincibleTimer",
              "star countdown, 35 -> 0 over ~730 frames. Replaces 'star_power_timer'"),
]

# --- Shinobi III (Genesis) ---------------------------------------------------------
# There is no public RAM map. This byte was found by recording all 64 KB of work RAM
# over a replay and keeping bytes that are zero before every health loss and start a
# countdown on the frame of it. It is set to 80 (or 64, depending on the attack) when
# health drops and counts down by one per frame, which is the period during which the
# player flashes. The same byte also runs from 48 after events that cost no health
# (knock-backs) and sits at 1 for ~25 frames at other moments, so the generator only
# uses runs that begin on a health loss.
#
# The Genesis core exposes 68000 work RAM word-swapped: the counter observed at raw
# offset $FF4164 of the memory block reads correctly when declared at $FF4165, which is
# how the emulator's variable reader was verified to return it (80 -> 1).

SHINOBI_CANDIDATES: List[Candidate] = [
    Candidate("hit_timer", 0xFF4165, "|u1", "(no public symbol)",
              "post-hit recovery countdown, 80 or 64 -> 0 over 81-103 frames"),
]

# --- Super Mario Bros 3 (NES) -----------------------------------------------------

SMB3_CANDIDATES: List[Candidate] = [
    *_array("object_id", 0x0671, 8, "|u1", "Level_ObjectID", "OBJ_* actor id per slot"),
    *_array("object_state", 0x0661, 8, "|u1", "Objects_State", "OBJSTATE_* per slot"),
    # Objects_DetStat is COLLISION bits, not visibility: $01 hit wall right, $02 hit wall
    # left, $04 hit ground, $08 hit ceiling, $80 on a 32px partition floor. The trailing
    # "on screen" in its .ds comment is vestigial. Kept for Enemy_attack heuristics only.
    *_array("object_detstat", 0x00D9, 8, "|u1", "Objects_DetStat",
            "collision bits: 1 wall-R, 2 wall-L, 4 ground, 8 ceiling, 0x80 partition"),
    # These are the actual visibility flags.
    *_array("object_sprhvis", 0x0651, 8, "|u1", "Objects_SprHVis",
            "bits set when each 8x16 sprite is horizontally off screen"),
    *_array("object_sprvvis", 0x0681, 8, "|u1", "Objects_SprVVis",
            "bits set when each 8x16 sprite is vertically off screen"),
    *_array("object_sprite_x", 0x00AC, 8, "|u1", "Objects_SpriteX", "screen X per slot"),
    *_array("object_sprite_y", 0x00B5, 8, "|u1", "Objects_SpriteY", "screen Y per slot"),
    *_array("object_x", 0x0091, 8, "|u1", "Objects_X", "level X low per slot"),
    *_array("object_x_hi", 0x0076, 8, "|u1", "Objects_XHi", "level X high per slot"),
    *_array("object_y", 0x00A3, 8, "|u1", "Objects_Y", "level Y low per slot"),
    *_array("object_y_hi", 0x0088, 8, "|u1", "Objects_YHi", "level Y high per slot"),
    Candidate("player_is_dying", 0x00F1, "|u1", "Player_IsDying",
              "0 no, 1 dying, 2 dropped off screen, 3 TIME UP"),
    *_array("object_player_hitstat", 0x0796, 8, "|u1", "Objects_PlayerHitStat",
            "which object hit the player"),
    Candidate("level_hautoscroll", 0x0580, "|u1", "Level_HAutoScroll",
              "-> Auto_scroll_started"),
    Candidate("player_halt_game", 0x00CE, "|u1", "Player_HaltGame",
              "dying / growing / shrinking"),
    Candidate("player_suit_lost", 0x0554, "|u1", "Player_SuitLost",
              "suit-lost poof counter"),
    Candidate("kill_tally", 0x05F4, "|u1", "Kill_Tally",
              "stomp chain (already shipped as stomp_counter)"),
    # Screen scroll. Needed as an INDEPENDENT geometric reference for validating the
    # per-slot visibility flags: Objects_SpriteX/Y hold stale values while an object is
    # not being drawn, so they cannot adjudicate. With the scroll position the object's
    # screen-relative X can be computed from Objects_X/XHi, exactly as is done for SMB1.
    Candidate("horz_scroll", 0x00FD, "|u1", "Horz_Scroll",
              "horizontal scroll of the name table"),
    Candidate("horz_scroll_hi", 0x0012, "|u1", "Horz_Scroll_Hi",
              "high byte of the horizontal scroll (current screen)"),
    Candidate("vert_scroll", 0x00FC, "|u1", "Vert_Scroll", "vertical scroll"),
    Candidate("vert_scroll_hi", 0x0013, "|u1", "Vert_Scroll_Hi",
              "high byte of the vertical scroll (vertical levels only)"),
]

# Addresses at/above $6000 in smb3.asm come from overlapping .org contexts and cannot be
# resolved unambiguously by static parsing. They are proposed separately and only ship if
# the harness confirms them.
SMB3_UNVERIFIED: List[Candidate] = [
    # VERIFIED: decodes to known SOBJ_* constants, and a PiranhaFireball appears exactly
    # while a VenusFireTrap is live in an adjacent slot.
    *_array("special_obj_id", 0x7FC6, 8, "|u1", "SpecialObj_ID", "SOBJ_* projectile ids"),
    # REJECTED: Inventory_Cards at $7C74 reads all-zero even on a cleared repetition, so
    # the static resolution of that overlapping .org context is wrong. The shipped
    # goal_cards_p1_{1,2,3} already detect level clearing correctly, so nothing is lost;
    # do NOT add this to data.json until a working address is found.
    # *_array("inventory_cards", 0x7C74, 3, "|u1", "Inventory_Cards", "goal cards"),
]

CANDIDATES: Dict[str, List[Candidate]] = {
    "SuperMarioBros-Nes": SMB1_CANDIDATES,
    "SuperMarioBros3-Nes": SMB3_CANDIDATES + SMB3_UNVERIFIED,
}


# --------------------------------------------------------------------- decode tables

#: Enemy/object ids for SMB1 ($00-$36), from SMBDIS.ASM: the named constants plus the
#: ``InitEnemyRoutines`` jump table, which covers the whole range including the entries
#: that have no symbolic constant. Ids with neither a constant nor a distinguishing init
#: routine are left as ``Unknown_0xNN`` rather than guessed; the validator flags any that
#: actually turn up in the data.
#:
#: Super Mario All-Stars reuses these ids verbatim in ``sprite_number_*`` (verified
#: empirically against mariostars replays: 13=PiranhaPlant, 6=Goomba, 2=BuzzyBeetle,
#: 0=GreenKoopa, 14=GreenParatroopa, 48=FlagpoleFlag, 49=StarFlag).
SMB1_ENEMY_IDS: Dict[int, str] = {
    0x00: "GreenKoopa", 0x01: "Unknown_0x01", 0x02: "BuzzyBeetle", 0x03: "RedKoopa",
    0x04: "Unknown_0x04", 0x05: "HammerBro", 0x06: "Goomba", 0x07: "Blooper",
    0x08: "BulletBill", 0x09: "Unknown_0x09", 0x0A: "GreyCheepCheep",
    0x0B: "RedCheepCheep", 0x0C: "Podoboo", 0x0D: "PiranhaPlant",
    0x0E: "GreenParatroopaJump", 0x0F: "RedParatroopa", 0x10: "GreenParatroopaFly",
    0x11: "Lakitu", 0x12: "Spiny", 0x13: "Unknown_0x13", 0x14: "FlyingCheepCheep",
    0x15: "BowserFlame", 0x16: "Fireworks", 0x17: "BulletBillCheepCheepFrenzy",
    0x18: "StopFrenzy", 0x19: "Unknown_0x19", 0x1A: "Unknown_0x1A",
    0x1B: "ShortFirebar", 0x1C: "ShortFirebar", 0x1D: "ShortFirebar",
    0x1E: "ShortFirebar", 0x1F: "LongFirebar",
    0x20: "Unknown_0x20", 0x21: "Unknown_0x21", 0x22: "Unknown_0x22",
    0x23: "Unknown_0x23", 0x24: "BalancePlatform", 0x25: "VerticalPlatform",
    0x26: "LargeLiftUp", 0x27: "LargeLiftDown", 0x28: "HorizontalPlatform",
    0x29: "DropPlatform", 0x2A: "HorizontalPlatform", 0x2B: "PlatformLiftUp",
    0x2C: "PlatformLiftDown", 0x2D: "Bowser", 0x2E: "PowerUpObject",
    0x2F: "VineObject", 0x30: "FlagpoleFlagObject", 0x31: "StarFlagObject",
    0x32: "JumpspringObject", 0x33: "BulletBillCannon", 0x34: "Unknown_0x34",
    0x35: "RetainerObject", 0x36: "EndOfEnemyObjects",
}

#: Moving platforms and lifts. They live in enemy slots but are scenery, not enemies.
SMB1_PLATFORM_IDS = frozenset(range(0x24, 0x2D))

#: Items, scenery and end-of-level objects that occupy an enemy slot.
SMB1_ITEM_SCENERY_IDS = frozenset({0x16, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x35, 0x36})

#: Spawner / control objects that occupy an enemy slot without ever being drawn.
#: They churn through a slot a frame at a time and must not produce Enemy_* events.
SMB1_SPAWNER_IDS = frozenset({0x17, 0x18})

#: The two ids a Bullet Bill can occupy: 0x08 when spawned by a frenzy and 0x33 when
#: fired from a cannon. Both are the same object -- measured over 120 mario replays,
#: runs of either id move at a median 1.5 px/frame, and 0x33 accounts for the large
#: majority (331 flying runs vs 90 for 0x08; on mariostars 283 vs 43). 0x33 was
#: previously classed as a spawner, which discarded most of the Bullet Bills in both
#: datasets outright.
#:
#: The id is shared with the stationary cannon object, which sits in a slot without
#: moving. Where per-slot X is available (NES) a motion test separates them; see
#: ``smb1._is_flying_bullet``.
SMB1_BULLET_IDS = frozenset({0x08, 0x33})

#: SMB1 ids that are projectiles rather than enemies proper. Bullet Bills are NOT here:
#: they are stompable, damage the player on contact, and behave as enemies. Bowser's
#: flame cannot be defeated and stays a projectile.
SMB1_PROJECTILE_IDS = frozenset({0x15})

#: The Piranha Plant, which hides inside its pipe for part of its cycle.
SMB1_PIRANHA_ID = 0x0D

#: Everything that is NOT an enemy for the purposes of Enemy_* events.
SMB1_NON_ENEMY_IDS = (
    SMB1_PLATFORM_IDS | SMB1_ITEM_SCENERY_IDS | SMB1_SPAWNER_IDS | SMB1_PROJECTILE_IDS
)

#: Objects_State values in SMB3, from smb3.asm.
SMB3_OBJECT_STATES: Dict[int, str] = {
    0: "DeadEmpty", 1: "Init", 2: "Normal", 3: "Shelled", 4: "Held",
    5: "Kicked", 6: "Killed", 7: "Squashed", 8: "PoofDeath",
}

#: Player_IsDying values in SMB3, from smb3.asm.
SMB3_IS_DYING: Dict[int, str] = {1: "Enemy", 2: "Fall", 3: "Timeout"}


# ------------------------------------------------------------------------- harness


def build_shadow_integration(dataset_dir: str, game: str, candidates, dest: str) -> str:
    """Copy an integration into ``dest`` with ``candidates`` merged into its data.json.

    Large files (ROMs, save states) are symlinked rather than copied so this stays cheap
    for the SNES and Genesis integrations.

    Returns:
        The directory to hand to ``retro.data.Integrations.add_custom_path``.
    """
    src = op.join(dataset_dir, "stimuli", game)
    if not op.isdir(src):
        raise FileNotFoundError(f"no integration at {src}")
    out_game = op.join(dest, game)
    os.makedirs(out_game, exist_ok=True)

    for entry in os.listdir(src):
        if entry == "data.json":
            continue
        source, target = op.join(src, entry), op.join(out_game, entry)
        if op.exists(target) or op.islink(target):
            continue
        if not op.isfile(source):
            continue
        if os.path.getsize(source) > 64 * 1024:
            os.symlink(op.realpath(source), target)
        else:
            shutil.copy2(source, target)

    with open(op.join(src, "data.json")) as f:
        data = json.load(f)
    info = data.setdefault("info", {})
    for cand in candidates:
        info[cand.name] = cand.as_json_entry()
    with open(op.join(out_game, "data.json"), "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)

    return dest


def replay_with_candidates(dataset_dir, game, bk2_path, candidates,
                           skip_first_step=False, workdir=None) -> dict:
    """Replay ``bk2_path`` against a shadow integration carrying ``candidates``.

    Returns the usual ``repetition_variables`` dict, with the candidate keys added.
    """
    tmp = workdir or tempfile.mkdtemp(prefix="vg_shadow_")
    build_shadow_integration(dataset_dir, game, candidates, tmp)
    retro.data.Integrations.add_custom_path(op.abspath(tmp))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        repvars, _, frames, _, _ = get_variables_from_replay(
            bk2_path, skip_first_step=skip_first_step, game=game,
            inttype=retro.data.Integrations.CUSTOM_ONLY)
    del frames
    return repvars

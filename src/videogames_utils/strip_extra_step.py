import glob, sys, os
import pandas as pd
import stable_retro as retro

env = None

def strip_first_step(bk2_in:str, bk2_out:str, strip_n_steps:int = 1):
    global env
    movie_in = retro.Movie(bk2_in)
    for i in range(strip_n_steps):
        movie_in.step()
    if env is None or env.gamename != movie_in.get_game():
        env = retro.make(movie_in.get_game())

    movie_out = retro.Movie(bk2_out, True, movie_in.players)
    movie_out.configure(env.gamename, env.em)
    movie_out.set_state(movie_in.get_state())
    while movie_in.step():
        for player in range(movie_in.players):
            for button in range(env.num_buttons):
                movie_out.set_key(button, movie_in.get_key(button, player), player)
        movie_out.step()
    movie_out.close()
    movie_in.close()


def main(path):
    events = glob.glob(path+'/sub-*/ses-*/func/*_events.tsv')
    for evt in events:
        print(f"process: {evt}")
        evt_df = pd.read_csv(evt, delimiter='\t')
        first_bk2 = str(evt_df.stim_file[0])
        if first_bk2.lower() != 'missing file' and len(first_bk2) and os.path.exists(first_bk2):
            strip_first_step(first_bk2, first_bk2)

if __name__ == '__main__':
    retro.data.add_custom_integration(sys.argv[1]+'/stimuli')
    main(sys.argv[1])

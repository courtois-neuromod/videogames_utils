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

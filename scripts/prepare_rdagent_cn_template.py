"""Compatibility entry point for the shared versioned CN compiler."""
from prepare_cn_scenario import compile_agent, load_profile, profile_path

if __name__ == '__main__':
    print(compile_agent(load_profile(profile_path())))

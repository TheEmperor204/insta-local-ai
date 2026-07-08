# Firejail profile for Instagram Auto-Poster
noroot
nonewprivs
seccomp
caps.drop all

# Block access to sensitive directories
blacklist ${HOME}/.ssh
blacklist ${HOME}/.gnupg
blacklist ${HOME}/.local/share/keyrings
blacklist ${HOME}/.mozilla
blacklist ${HOME}/.cache/mozilla

# Add your own blacklists here for other apps:
# blacklist ${HOME}/path/to/other/app

private-tmp

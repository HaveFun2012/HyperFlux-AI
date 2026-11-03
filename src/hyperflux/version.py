"""The HyperFlux version. Bump this before tagging a release (the tag must be "v" + this).

The release workflow refuses to build if the tag and this value differ, and the
in-app updater compares it with the newest GitHub release.
"""

__version__ = "1.0.0"

# Where releases are published, for the update check.
GITHUB_REPO = "HaveFun2012/HyperFlux-AI"

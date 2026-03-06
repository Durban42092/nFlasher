from setuptools import setup, find_packages

setup(
    name             = "nflasher",
    version          = "1.0.0",
    description      = "Samsung device flash tool for Linux (nphonecli/odin4/heimdall frontend)",
    long_description = open("README.md").read(),
    long_description_content_type = "text/markdown",
    author           = "nFlasher Contributors",
    license          = "GPL-3.0",
    url              = "https://github.com/nflasher/nflasher",
    packages         = find_packages(),
    python_requires  = ">=3.10",
    install_requires = [
        "pyusb>=1.2.1",
    ],
    extras_require = {
        "dev": ["pytest", "mypy"],
    },
    entry_points = {
        "console_scripts": [
            "nflasher = nflasher.ui:main",
        ],
        "gui_scripts": [
            "nflasher-gui = nflasher.ui:main",
        ],
    },
    classifiers = [
        "Development Status :: 4 - Beta",
        "Environment :: X11 Applications :: GTK",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Hardware",
        "Topic :: Utilities",
    ],
    data_files = [
        ("share/applications", ["data/io.github.nflasher.desktop"]),
        ("share/icons/hicolor/scalable/apps", ["data/nflasher.svg"]),
    ],
)

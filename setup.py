from setuptools import setup, find_packages

setup(
    name="rbxsync",
    version="3.0.0",
    description="RBXSync - Roblox Creator Store Asset Synchronization Tool & Textual TUI",
    py_modules=["uploader", "tui", "gui", "watcher"],
    install_requires=[
        "textual>=0.80.0",
        "rich>=14.0.0",
        "requests",
        "python-dotenv",
        "watchdog",
        "Pillow",
    ],
    entry_points={
        "console_scripts": [
            "rbxsync=tui:main",
            "rbxsync-cli=uploader:main",
            "easy-upload=tui:main",
            "roblox-upload=tui:main",
            "roblox-uploader=uploader:main",
        ],
    },
)

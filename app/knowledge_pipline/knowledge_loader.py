import os

def load_workflow_file(filename : str) -> str:

    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    return f"Error : {filename} documentation file is missing."
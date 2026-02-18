from pathlib import Path
from typing import List

def get_playlists_id(filename: Path) -> List[str]:
    """
    :param filename: Path to the txt file with ids per line
    :type filename: Path
    """
    list_of_ids = []
    with open(filename, "r") as file:
        for line in file:
            list_of_ids.append(line.strip())
    
    return list_of_ids
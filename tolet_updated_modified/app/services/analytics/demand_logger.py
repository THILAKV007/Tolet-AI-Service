import os
from datetime import datetime


class DemandLogger:

    def __init__(self):

        # ===================================
        # Folder Path
        # ===================================
        self.folder_path = "data"

        # ===================================
        # File Path
        # ===================================
        self.file_path = (
            "data/user_demand_locations.txt"
        )

        # ===================================
        # Create Folder if Missing
        # ===================================
        os.makedirs(

            self.folder_path,

            exist_ok=True
        )

    def log_unavailable_location(

        self,

        query: str,

        location: str
    ):

        try:

            # ===================================
            # Current Time
            # ===================================
            timestamp = datetime.now().strftime(

                "%Y-%m-%d %H:%M:%S"
            )

            # ===================================
            # Log Line
            # ===================================
            log_line = (

                f"[{timestamp}] "

                f"Location: {location} | "

                f"Query: {query}\n"
            )

            # ===================================
            # Append to File
            # ===================================
            with open(

                self.file_path,

                "a",

                encoding="utf-8"
            ) as file:

                file.write(log_line)

        except Exception as error:

            print(

                "Demand Logger Error:",

                error
            )
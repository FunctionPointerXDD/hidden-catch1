from typing import Literal

GameStatus = Literal[
    "waiting_upload",
    "waiting_puzzle",
    "waiting_next_stage",
    "playing",
    "finished",
]
Difficulty = Literal["easy", "normal", "difficult"]
UploadAnalysisStatus = Literal["pending", "processing", "succeeded", "failed"]

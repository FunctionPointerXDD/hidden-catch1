from typing import Literal

GameStatus = Literal[
    "waiting_upload",
    "waiting_puzzle",
    "waiting_next_stage",
    "playing",
    "finished",
    "failed",
]
Difficulty = Literal["easy", "normal", "difficult"]
UploadAnalysisStatus = Literal["pending", "processing", "completed", "failed"]

"""모든 지표 플러그인의 베이스 클래스"""

from abc import ABC, abstractmethod
import pandas as pd


class BaseIndicator(ABC):
    category: str = ""
    name: str = ""
    description: str = ""

    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """지표를 계산하여 DataFrame에 컬럼 추가"""

    @abstractmethod
    def get_signal(self, df: pd.DataFrame) -> dict:
        """최신 데이터 기반 시그널 반환.
        Returns: {
            "name": str,
            "value": any,
            "signal": str (한글 설명),
            "direction": "buy" | "sell" | "neutral",
            "score": int (0~100, 50=중립),
            "confidence": float (0~1),
        }
        """

    @classmethod
    def default_params(cls) -> dict:
        """DB에 저장할 기본 파라미터"""
        return {}

    def _safe_latest(self, df: pd.DataFrame, col: str):
        if col in df.columns and len(df) > 0:
            val = df[col].iloc[-1]
            if pd.notna(val):
                return val
        return None

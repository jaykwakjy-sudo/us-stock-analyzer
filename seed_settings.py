"""DB 설정 시드 스크립트 — 한 번만 실행하여 기본 지표/가중치 설정을 DB에 저장"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from data.database import save_setting, get_setting
from analysis.engine import get_default_indicator_config, get_default_scoring_weights


def seed():
    if not get_setting("indicator_config"):
        config = get_default_indicator_config()
        save_setting("indicator_config", config)
        print(f"[OK] indicator_config 시드 완료 ({len(config)}개 지표)")
    else:
        print("[SKIP] indicator_config 이미 존재")

    if not get_setting("scoring_weights"):
        weights = get_default_scoring_weights()
        save_setting("scoring_weights", weights)
        print("[OK] scoring_weights 시드 완료")
    else:
        print("[SKIP] scoring_weights 이미 존재")

    if not get_setting("fundamental_params"):
        fund_params = {
            "valuation": {"pe_expensive": 35, "pe_cheap": 15},
            "growth": {},
            "quality": {},
            "earnings": {},
            "weights": {"valuation": 0.3, "growth": 0.3, "quality": 0.2, "earnings": 0.2},
        }
        save_setting("fundamental_params", fund_params)
        print("[OK] fundamental_params 시드 완료")
    else:
        print("[SKIP] fundamental_params 이미 존재")

    print("\n시드 완료. 모든 분석 파라미터는 Settings 페이지에서 변경 가능합니다.")


if __name__ == "__main__":
    seed()

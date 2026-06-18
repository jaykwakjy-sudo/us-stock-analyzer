"""FinRL 모델 학습 스크립트 — 주 1회 실행

watchlist 종목에 대해 5개 DRL 에이전트를 학습하고
trained_models/ 에 저장. 학습 완료 후 DB에 결과 기록.

실행: python3 -m trading.finrl_trainer
"""
from __future__ import annotations

import os
import sys
import json
import logging
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("finrl_trainer")

TRAINED_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "trained_models")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")

INDICATORS = [
    "macd", "boll_ub", "boll_lb", "rsi_30",
    "cci_30", "dx_30", "close_30_sma", "close_60_sma",
]

ALGORITHMS = ["a2c", "ppo", "ddpg", "td3", "sac"]

ALGO_PARAMS = {
    "a2c": {"n_steps": 5, "ent_coef": 0.01, "learning_rate": 0.0007},
    "ppo": {"n_steps": 2048, "ent_coef": 0.01, "learning_rate": 0.00025, "batch_size": 128},
    "ddpg": {"batch_size": 128, "buffer_size": 50000, "learning_rate": 0.001},
    "td3": {"batch_size": 100, "buffer_size": 1000000, "learning_rate": 0.001},
    "sac": {"batch_size": 128, "buffer_size": 100000, "learning_rate": 0.0001,
            "learning_starts": 100, "ent_coef": "auto_0.1"},
}


def load_config():
    from data.database import get_client, get_setting, get_watchlist

    db = get_client()
    trading_config = get_setting("trading_config") or {}
    finrl_config = get_setting("finrl_config") or {}
    watchlist = get_watchlist()
    tickers = [w["ticker"] for w in watchlist]

    config = {
        "tickers": tickers,
        "train_start": finrl_config.get("train_start", "2020-01-01"),
        "train_end": finrl_config.get("train_end", "2025-12-31"),
        "trade_start": finrl_config.get("trade_start", "2026-01-01"),
        "trade_end": finrl_config.get("trade_end", "2026-06-18"),
        "total_timesteps": finrl_config.get("total_timesteps", 50000),
        "initial_amount": trading_config.get("initial_capital", 100000),
        "hmax": finrl_config.get("hmax", 100),
        "algorithms": finrl_config.get("algorithms", ALGORITHMS),
        "indicators": finrl_config.get("indicators", INDICATORS),
    }
    return db, config


def fetch_and_preprocess(tickers, train_start, train_end, trade_end, indicators):
    from finrl.meta.preprocessor.yahoodownloader import YahooDownloader
    from finrl.meta.preprocessor.preprocessors import FeatureEngineer, data_split
    import itertools

    logger.info(f"데이터 다운로드: {len(tickers)}개 종목, {train_start} ~ {trade_end}")

    df_raw = YahooDownloader(
        start_date=train_start,
        end_date=trade_end,
        ticker_list=tickers,
    ).fetch_data()

    logger.info(f"원시 데이터: {len(df_raw)}행")

    fe = FeatureEngineer(
        use_technical_indicator=True,
        tech_indicator_list=indicators,
        use_vix=False,
        use_turbulence=False,
        user_defined_feature=False,
    )
    processed = fe.preprocess_data(df_raw)
    import numpy as np
    processed = processed.replace([np.inf, -np.inf], 0)

    list_ticker = processed["tic"].unique().tolist()
    list_date = list(
        pd.date_range(processed["date"].min(), processed["date"].max()).astype(str)
    )
    combination = list(itertools.product(list_date, list_ticker))
    processed_full = pd.DataFrame(combination, columns=["date", "tic"]).merge(
        processed, on=["date", "tic"], how="left"
    )
    processed_full = processed_full[processed_full["date"].isin(processed["date"])]
    processed_full = processed_full.sort_values(["date", "tic"])
    processed_full = processed_full.fillna(0)

    logger.info(f"전처리 완료: {len(processed_full)}행, 종목={len(list_ticker)}개")
    return processed_full


def build_env(df, stock_dim, indicators, initial_amount, hmax):
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv

    state_space = 1 + 2 * stock_dim + len(indicators) * stock_dim

    env_kwargs = {
        "hmax": hmax,
        "initial_amount": initial_amount,
        "num_stock_shares": [0] * stock_dim,
        "buy_cost_pct": [0.001] * stock_dim,
        "sell_cost_pct": [0.001] * stock_dim,
        "state_space": state_space,
        "stock_dim": stock_dim,
        "tech_indicator_list": indicators,
        "action_space": stock_dim,
        "reward_scaling": 1e-4,
    }

    env = StockTradingEnv(df=df, **env_kwargs)
    return env, env_kwargs


def train_agents(env, config):
    from finrl.agents.stablebaselines3.models import DRLAgent
    from stable_baselines3.common.logger import configure
    from stable_baselines3.common.vec_env import DummyVecEnv

    os.makedirs(TRAINED_MODEL_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    sb_env = DummyVecEnv([lambda: env])
    results = {}

    for algo_name in config["algorithms"]:
        logger.info(f"=== {algo_name.upper()} 학습 시작 ===")
        try:
            agent = DRLAgent(env=sb_env)
            params = ALGO_PARAMS.get(algo_name, {})
            model = agent.get_model(algo_name, model_kwargs=params)

            log_path = os.path.join(RESULTS_DIR, algo_name)
            os.makedirs(log_path, exist_ok=True)
            new_logger = configure(log_path, ["stdout", "csv"])
            model.set_logger(new_logger)

            trained = agent.train_model(
                model=model,
                tb_log_name=algo_name,
                total_timesteps=config["total_timesteps"],
            )

            save_path = os.path.join(TRAINED_MODEL_DIR, f"agent_{algo_name}")
            trained.save(save_path)
            results[algo_name] = {"status": "success", "path": save_path}
            logger.info(f"{algo_name.upper()} 학습 완료 → {save_path}")

        except Exception as e:
            logger.error(f"{algo_name.upper()} 학습 실패: {e}")
            results[algo_name] = {"status": "failed", "error": str(e)}

    return results


def backtest(env_kwargs, trade_data, config):
    from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
    from finrl.agents.stablebaselines3.models import DRLAgent
    from stable_baselines3 import A2C, DDPG, PPO, SAC, TD3

    ALGO_CLASSES = {"a2c": A2C, "ddpg": DDPG, "ppo": PPO, "sac": SAC, "td3": TD3}

    e_trade = StockTradingEnv(
        df=trade_data,
        **env_kwargs,
    )

    backtest_results = {}

    for algo_name in config["algorithms"]:
        model_path = os.path.join(TRAINED_MODEL_DIR, f"agent_{algo_name}")
        if not os.path.exists(model_path + ".zip"):
            continue

        try:
            model_cls = ALGO_CLASSES[algo_name]
            trained = model_cls.load(model_path)
            df_account, df_actions = DRLAgent.DRL_prediction(
                model=trained, environment=e_trade
            )
            final_value = df_account["account_value"].iloc[-1]
            initial = config["initial_amount"]
            pnl_pct = (final_value - initial) / initial * 100

            backtest_results[algo_name] = {
                "final_value": round(final_value, 2),
                "pnl_pct": round(pnl_pct, 2),
                "total_trades": len(df_actions),
            }
            logger.info(f"[백테스트] {algo_name.upper()}: "
                        f"${final_value:,.2f} ({pnl_pct:+.2f}%)")
        except Exception as e:
            logger.error(f"[백테스트] {algo_name.upper()} 실패: {e}")

    return backtest_results


def save_results(db, train_results, backtest_results, config):
    best_algo = None
    best_pnl = None

    for algo, result in backtest_results.items():
        pnl = result.get("pnl_pct")
        if pnl is not None and (best_pnl is None or pnl > best_pnl):
            best_pnl = pnl
            best_algo = algo

    record = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "tickers": config["tickers"],
        "train_period": f"{config['train_start']} ~ {config['train_end']}",
        "trade_period": f"{config['trade_start']} ~ {config['trade_end']}",
        "total_timesteps": config["total_timesteps"],
        "train_results": train_results,
        "backtest_results": backtest_results,
        "best_algorithm": best_algo,
        "best_pnl_pct": best_pnl if best_pnl is not None else 0,
    }

    db.table("settings").upsert(
        {"key": "finrl_results", "value": record},
        on_conflict="key",
    ).execute()

    if best_algo:
        db.table("settings").upsert(
            {"key": "finrl_config", "value": {
                **config,
                "active_algorithm": best_algo,
            }},
            on_conflict="key",
        ).execute()

    if best_algo:
        logger.info(f"최적 알고리즘: {best_algo.upper()} ({best_pnl:+.2f}%)")
    else:
        logger.warning("백테스트 결과 없음 — 최적 알고리즘 미선정")
    return best_algo


def main():
    logger.info("=" * 60)
    logger.info("FinRL 학습 파이프라인 시작")
    logger.info("=" * 60)

    db, config = load_config()
    logger.info(f"종목: {config['tickers']}")
    logger.info(f"학습기간: {config['train_start']} ~ {config['train_end']}")
    logger.info(f"timesteps: {config['total_timesteps']}")

    from finrl.meta.preprocessor.preprocessors import data_split

    processed = fetch_and_preprocess(
        config["tickers"],
        config["train_start"],
        config["train_end"],
        config["trade_end"],
        config["indicators"],
    )

    train_data = data_split(processed, config["train_start"], config["train_end"])
    trade_data = data_split(processed, config["trade_start"], config["trade_end"])
    logger.info(f"학습 데이터: {len(train_data)}행, 테스트: {len(trade_data)}행")

    stock_dim = len(train_data["tic"].unique())
    train_env, env_kwargs = build_env(
        train_data, stock_dim, config["indicators"],
        config["initial_amount"], config["hmax"],
    )

    train_results = train_agents(train_env, config)

    backtest_results = backtest(env_kwargs, trade_data, config)

    best = save_results(db, train_results, backtest_results, config)

    logger.info("=" * 60)
    logger.info(f"학습 완료. 최적 모델: {best}")
    logger.info("trading_config에서 strategy를 'finrl'로 변경하면 적용됩니다.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

"""FinRL-X 모델 학습 스크립트 — Weight-Centric DRL 파이프라인

StockPortfolioEnv(가중치 출력)로 DRL 에이전트를 학습하고
bt 라이브러리로 백테스트. 학습 완료 후 DB에 결과 기록.

실행: python3 -m trading.finrl_trainer
"""
from __future__ import annotations

import os
import sys
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

import numpy as np
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


@dataclass
class WeightResult:
    """FinRL-X 스타일 가중치 결과"""
    algorithm: str
    weights: pd.DataFrame
    metadata: dict = field(default_factory=dict)


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
        "transaction_cost": finrl_config.get("transaction_cost", 0.001),
        "rebalance_freq": finrl_config.get("rebalance_freq", "weekly"),
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


def build_portfolio_env(df, stock_dim, indicators):
    """가중치 기반 포트폴리오 환경 구성"""
    import gymnasium as gym
    from gymnasium import spaces

    dates = sorted(df["date"].unique())
    tickers = sorted(df["tic"].unique())

    class WeightEnv(gym.Env):
        """action = 종목별 비율 → softmax 정규화 → 포트폴리오 리턴"""

        def __init__(self):
            super().__init__()
            self.stock_dim = stock_dim
            self.action_space = spaces.Box(
                low=0, high=1, shape=(stock_dim,), dtype=np.float32
            )
            obs_dim = stock_dim * (1 + len(indicators))
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
            )
            self.dates = dates
            self.tickers = tickers
            self.df = df
            self.indicators = indicators
            self.day = 0
            self.portfolio_value = 1.0
            self.weights = np.ones(stock_dim) / stock_dim

        def _get_obs(self):
            day_data = self.df[self.df["date"] == self.dates[self.day]]
            day_data = day_data.sort_values("tic")

            closes = day_data["close"].values.astype(np.float32)
            closes = np.nan_to_num(closes, nan=0.0)

            tech_values = []
            for ind in self.indicators:
                if ind in day_data.columns:
                    vals = day_data[ind].values.astype(np.float32)
                else:
                    vals = np.zeros(self.stock_dim, dtype=np.float32)
                tech_values.append(np.nan_to_num(vals, nan=0.0))

            return np.concatenate([closes] + tech_values)

        def _get_returns(self):
            if self.day == 0:
                return np.zeros(self.stock_dim)
            curr = self.df[self.df["date"] == self.dates[self.day]].sort_values("tic")["close"].values
            prev = self.df[self.df["date"] == self.dates[self.day - 1]].sort_values("tic")["close"].values
            with np.errstate(divide="ignore", invalid="ignore"):
                returns = np.where(prev > 0, curr / prev - 1, 0)
            return np.nan_to_num(returns, nan=0.0)

        def reset(self, seed=None, options=None):
            super().reset(seed=seed)
            self.day = 0
            self.portfolio_value = 1.0
            self.weights = np.ones(self.stock_dim) / self.stock_dim
            return self._get_obs(), {}

        def step(self, action):
            weights = np.clip(action, 0, None)
            w_sum = weights.sum()
            if w_sum > 0:
                weights = weights / w_sum
            else:
                weights = np.ones(self.stock_dim) / self.stock_dim

            self.weights = weights
            self.day += 1

            done = self.day >= len(self.dates) - 1
            if done:
                self.day = len(self.dates) - 1

            returns = self._get_returns()
            port_return = np.dot(weights, returns)
            self.portfolio_value *= (1 + port_return)

            obs = self._get_obs()
            return obs, port_return, done, done, {
                "portfolio_value": self.portfolio_value,
                "weights": weights.tolist(),
            }

    return WeightEnv()


def train_agents(env, config):
    from finrl.agents.stablebaselines3.models import DRLAgent
    from stable_baselines3.common.logger import configure
    from stable_baselines3.common.vec_env import DummyVecEnv

    os.makedirs(TRAINED_MODEL_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    sb_env = DummyVecEnv([lambda: env])
    results = {}

    for algo_name in config["algorithms"]:
        logger.info(f"=== {algo_name.upper()} 학습 시작 (Weight-Centric) ===")
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


def generate_weight_signals(trade_data, config):
    """학습된 모델로 거래 기간 가중치 시그널 생성"""
    from stable_baselines3 import A2C, DDPG, PPO, SAC, TD3

    ALGO_CLASSES = {"a2c": A2C, "ddpg": DDPG, "ppo": PPO, "sac": SAC, "td3": TD3}

    dates = sorted(trade_data["date"].unique())
    tickers = sorted(trade_data["tic"].unique())
    stock_dim = len(tickers)
    weight_results = {}

    for algo_name in config["algorithms"]:
        model_path = os.path.join(TRAINED_MODEL_DIR, f"agent_{algo_name}")
        if not os.path.exists(model_path + ".zip"):
            continue

        try:
            model_cls = ALGO_CLASSES[algo_name]
            model = model_cls.load(model_path)

            env = build_portfolio_env(trade_data, stock_dim, config["indicators"])
            obs, _ = env.reset()
            all_weights = []
            weight_dates = []

            for date in dates[:-1]:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, done, truncated, info = env.step(action)

                weights = np.clip(action, 0, None)
                w_sum = weights.sum()
                weights = weights / w_sum if w_sum > 0 else np.ones(stock_dim) / stock_dim

                all_weights.append(weights)
                weight_dates.append(date)

                if done:
                    break

            weights_df = pd.DataFrame(all_weights, columns=tickers, index=weight_dates)
            weights_df.index.name = "date"

            weight_results[algo_name] = WeightResult(
                algorithm=algo_name,
                weights=weights_df,
                metadata={"total_days": len(weight_dates)},
            )
            logger.info(f"[가중치] {algo_name.upper()}: {len(weight_dates)}일 시그널 생성")

        except Exception as e:
            logger.error(f"[가중치] {algo_name.upper()} 실패: {e}")

    return weight_results


def backtest_with_bt(weight_results, trade_data, config):
    """bt 라이브러리로 가중치 기반 백테스트"""
    try:
        import bt
        return _bt_backtest(bt, weight_results, trade_data, config)
    except ImportError:
        logger.warning("bt 미설치 — 단순 백테스트 사용")
        return _simple_backtest(weight_results, trade_data, config)


def _bt_backtest(bt, weight_results, trade_data, config):
    tickers = sorted(trade_data["tic"].unique())
    price_df = trade_data.pivot(index="date", columns="tic", values="close")
    price_df.index = pd.to_datetime(price_df.index)
    price_df = price_df[tickers]

    backtest_results = {}

    for algo_name, wr in weight_results.items():
        try:
            weights_df = wr.weights.copy()
            weights_df.index = pd.to_datetime(weights_df.index)
            weights_df = weights_df.reindex(price_df.index, method="ffill")
            weights_df = weights_df.fillna(1.0 / len(tickers))

            strategy = bt.Strategy(
                algo_name.upper(),
                [
                    bt.algos.RunDaily(),
                    bt.algos.SelectAll(),
                    bt.algos.WeighSpecified(**{
                        col: weights_df[col] for col in weights_df.columns
                    }),
                    bt.algos.Rebalance(),
                ],
            )

            test = bt.Backtest(strategy, price_df, initial_capital=config["initial_amount"])
            result = bt.run(test)

            stats = result.stats
            name_key = algo_name.upper()
            total_return = float(stats.loc["total_return", name_key]) * 100
            final_value = config["initial_amount"] * (1 + total_return / 100)
            sharpe = float(stats.loc["daily_sharpe", name_key]) if "daily_sharpe" in stats.index else 0
            max_dd = float(stats.loc["max_drawdown", name_key]) * 100 if "max_drawdown" in stats.index else 0

            backtest_results[algo_name] = {
                "final_value": round(final_value, 2),
                "pnl_pct": round(total_return, 2),
                "sharpe_ratio": round(sharpe, 3),
                "max_drawdown": round(max_dd, 2),
            }
            logger.info(
                f"[bt 백테스트] {algo_name.upper()}: "
                f"${final_value:,.2f} ({total_return:+.2f}%), "
                f"Sharpe={sharpe:.3f}, MaxDD={max_dd:.2f}%"
            )

        except Exception as e:
            logger.error(f"[bt 백테스트] {algo_name.upper()} 실패: {e}")

    return backtest_results


def _simple_backtest(weight_results, trade_data, config):
    """bt 없을 때 단순 가중치 백테스트"""
    tickers = sorted(trade_data["tic"].unique())
    dates = sorted(trade_data["date"].unique())
    price_df = trade_data.pivot(index="date", columns="tic", values="close")
    price_df = price_df[tickers]

    backtest_results = {}

    for algo_name, wr in weight_results.items():
        try:
            portfolio_value = config["initial_amount"]
            weights_df = wr.weights

            for i in range(1, len(dates)):
                date = dates[i]
                prev_date = dates[i - 1]

                if prev_date in weights_df.index:
                    weights = weights_df.loc[prev_date].values
                else:
                    weights = np.ones(len(tickers)) / len(tickers)

                curr_prices = price_df.loc[date].values
                prev_prices = price_df.loc[prev_date].values

                with np.errstate(divide="ignore", invalid="ignore"):
                    returns = np.where(prev_prices > 0, curr_prices / prev_prices - 1, 0)
                returns = np.nan_to_num(returns, nan=0.0)

                port_return = np.dot(weights, returns)
                portfolio_value *= (1 + port_return)

            pnl_pct = (portfolio_value - config["initial_amount"]) / config["initial_amount"] * 100

            backtest_results[algo_name] = {
                "final_value": round(portfolio_value, 2),
                "pnl_pct": round(pnl_pct, 2),
            }
            logger.info(
                f"[단순 백테스트] {algo_name.upper()}: "
                f"${portfolio_value:,.2f} ({pnl_pct:+.2f}%)"
            )

        except Exception as e:
            logger.error(f"[단순 백테스트] {algo_name.upper()} 실패: {e}")

    return backtest_results


def save_results(db, train_results, backtest_results, weight_results, config):
    best_algo = None
    best_pnl = None

    for algo, result in backtest_results.items():
        pnl = result.get("pnl_pct")
        if pnl is not None and (best_pnl is None or pnl > best_pnl):
            best_pnl = pnl
            best_algo = algo

    best_weights = None
    if best_algo and best_algo in weight_results:
        wr = weight_results[best_algo]
        last_weights = wr.weights.iloc[-1].to_dict()
        best_weights = {k: round(float(v), 4) for k, v in last_weights.items()}

    record = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "framework": "finrl-x",
        "mode": "weight-centric",
        "tickers": config["tickers"],
        "train_period": f"{config['train_start']} ~ {config['train_end']}",
        "trade_period": f"{config['trade_start']} ~ {config['trade_end']}",
        "total_timesteps": config["total_timesteps"],
        "train_results": train_results,
        "backtest_results": backtest_results,
        "best_algorithm": best_algo,
        "best_pnl_pct": best_pnl if best_pnl is not None else 0,
        "best_weights": best_weights,
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
                "framework": "finrl-x",
                "mode": "weight-centric",
            }},
            on_conflict="key",
        ).execute()

    if best_algo:
        logger.info(f"최적 알고리즘: {best_algo.upper()} ({best_pnl:+.2f}%)")
        if best_weights:
            logger.info(f"최종 가중치: {best_weights}")
    else:
        logger.warning("백테스트 결과 없음 — 최적 알고리즘 미선정")
    return best_algo


def main():
    logger.info("=" * 60)
    logger.info("FinRL-X 학습 파이프라인 시작 (Weight-Centric)")
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
    train_env = build_portfolio_env(train_data, stock_dim, config["indicators"])

    train_results = train_agents(train_env, config)

    weight_results = generate_weight_signals(trade_data, config)

    backtest_results = backtest_with_bt(weight_results, trade_data, config)

    best = save_results(db, train_results, backtest_results, weight_results, config)

    logger.info("=" * 60)
    logger.info(f"학습 완료. 최적 모델: {best}")
    logger.info("trading_config에서 strategy를 'finrl'로 변경하면 적용됩니다.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()

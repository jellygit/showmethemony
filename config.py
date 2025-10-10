# config.py
BUY_COMMISSION_RATE = 0.0025
SELL_TAX_RATE = 0.0025
TICKER_NAMES = {
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust",
    "IEF": "iShares 7-10 Year Treasury Bond ETF",
    "BIL": "SPDR Bloomberg 1-3 Month T-Bill ETF",
    "IWD": "iShares Russell 1000 Value ETF",
    "GLD": "SPDR Gold Shares",
    "SHY": "iShares 1-3 Year Treasury Bond ETF",
    "IWM": "iShares Russell 2000 ETF",
    "VGK": "Vanguard FTSE Europe ETF",
    "EWJ": "iShares MSCI Japan ETF",
    "VWO": "Vanguard FTSE Emerging Markets ETF",
    "VNQ": "Vanguard Real Estate ETF",
    "GSG": "iShares S&P GSCI Commodity-Indexed Trust",
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "HYG": "iShares iBoxx $ High Yield Corporate Bond ETF",
    "LQD": "iShares iBoxx $ Investment Grade Corporate Bond ETF",
    "AGG": "iShares Core U.S. Aggregate Bond ETF",
    "EEM": "iShares MSCI Emerging Markets ETF",
    "EFA": "iShares MSCI EAFE ETF",
    "QLD": "ProShares Ultra QQQ",
    "BND": "Vanguard Total Bond Market ETF",
}
STRATEGY_ASSETS = {
    "haa": {
        "offensive": ["SPY", "QQQ"],
        "defensive": ["IEF", "BIL"],
        "canary": ["SPY"],
    },
    "daa": {
        "offensive": [
            "SPY",
            "IWM",
            "QQQ",
            "VGK",
            "EWJ",
            "VWO",
            "VNQ",
            "GSG",
            "GLD",
            "TLT",
            "HYG",
            "LQD",
        ],
        "defensive": ["IEF", "LQD", "TLT"],
        "canary": ["SPY", "EEM", "EFA", "AGG"],
    },
    "laa": {
        "core": ["IWD", "GLD", "IEF"],
        "offensive": ["SPY"],
        "defensive": ["SHY"],
        "canary": ["SPY"],
    },
}

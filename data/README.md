# Data Directory

This public repository intentionally excludes `data/raw/` and `data/processed/`.

Users must obtain market and fundamental data under the provider's licence and
populate the local cache through the project scripts. Do not redistribute paid
Tushare data, personal records or provider credentials.

The code treats missing, permission-denied and offline data as explicit health
states. An empty or failed response must not be interpreted as a zero value or
as evidence that no risk event exists.

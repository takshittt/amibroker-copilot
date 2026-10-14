---
title: Intraday EMA crossover, long and short, flat by the close
timeframe: 5min
market: nse_fo
tags: [intraday, crossover, long-short, time]
---
Trades an EMA crossover in both directions on 5-minute bars. Entries are
allowed only inside a time window, and every open trade is closed at the
exit time so nothing is carried overnight. Trades are filled at the
close of the signal bar. All three times are parameters.

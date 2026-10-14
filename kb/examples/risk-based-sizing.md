---
title: Sizing each trade by the distance to its stop
timeframe: daily
market: nse_eq
tags: [sizing, stops, atr, risk]
---
A simple trend entry where the size of each trade depends on its stop.
The stop sits a multiple of ATR below the entry, and the position is
sized so that hitting the stop loses a fixed percentage of the account.
A wider stop therefore means a smaller position.

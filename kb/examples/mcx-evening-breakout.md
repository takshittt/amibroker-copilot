---
title: Intraday breakout on a commodity, flat before the evening close
timeframe: 15min
market: mcx
tags: [intraday, breakout, commodity, stops, time]
---
Buys when price trades above the highest high of the earlier bars on
15-minute data, with the entry filled at that level. An ATR trailing
stop follows the trade, and any open trade is closed at the exit time.
MCX closes at a different time in summer and winter, so the last-entry
and exit times are parameters and should be set from the market preset.

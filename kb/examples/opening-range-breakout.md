---
title: Opening range breakout with a stop at the other side of the range
timeframe: 5min
market: nse_fo
tags: [intraday, breakout, opening-range, stops, time]
---
Marks the high and low of the first part of the session, then buys when
price trades above that high. The trade leaves if price falls to the
range low, or at the exit time. The entry is filled at the range high,
or at the open when the bar opens above it, and the stop is filled the
same way at the range low. The range is fixed from earlier bars only, so
nothing looks ahead. After a stop the strategy can enter again the same
day if price breaks out again.

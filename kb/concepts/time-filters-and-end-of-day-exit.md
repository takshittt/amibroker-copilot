---
title: Time filters and the end-of-day exit
tags: [intraday, time, exit]
---
TimeNum gives the time of each bar as a number in the form HHMMSS, so
9:15 in the morning is 91500 and 3:15 in the afternoon is 151500. It is
compared like any other number.

An intraday strategy normally needs three times: when entries may start,
when they must stop, and when any open trade is closed. Keep them in
parameters at the top so they can be changed for another market.

```afl
FirstEntryTime = ParamTime("First entry", "09:30");
LastEntryTime = ParamTime("Last entry", "14:30");
ExitTime = ParamTime("Exit time", "15:15");

SetTradeDelays(0, 0, 0, 0);
tn = TimeNum();
CanEnter = tn >= FirstEntryTime AND tn <= LastEntryTime;

Buy = Cross(EMA(Close, 9), EMA(Close, 21)) AND CanEnter;
Sell = Cross(EMA(Close, 21), EMA(Close, 9)) OR tn >= ExitTime;
BuyPrice = Close;
SellPrice = Close;
```

The exit time belongs in the Sell condition, and in Cover for short
trades. A filter on entries alone does not close anything: a trade
opened at 14:25 would still be open at the close and the backtest would
carry it overnight.

Choose an exit time a few bars before the session ends, so the exit bar
exists and can be traded.

The right times depend on the market. They come from the market preset
chosen for the strategy, not from memory.

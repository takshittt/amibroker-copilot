---
title: Look-ahead bias, and how it gets into a backtest
tags: [look-ahead, backtest, ref]
---
A backtest has look-ahead bias when a signal uses information that was
not available at the time of the trade. The results look excellent and
cannot be repeated in real trading. AmiBroker does not warn about it.

The common ways it happens in AFL:

- Ref with a positive number, which reads later bars. Earlier bars are
  read with a negative number.
- Zig, Peak, Trough, PeakBars and TroughBars. A peak is only known to be
  a peak after price has fallen away from it, so these functions change
  their past values as new bars arrive.
- Filling at the open of the same bar whose close produced the signal.
- Using a whole day's high or low before the day has ended, on an
  intraday chart.

```afl
SetTradeDelays(1, 1, 1, 1);
Breakout = Close > Ref(HHV(High, 20), -1);
Buy = Breakout;
Sell = Close < Ref(LLV(Low, 10), -1);
BuyPrice = Open;
SellPrice = Open;
```

The `Ref(..., -1)` matters here. HHV includes the current bar, so
without it the close could never be above the highest high and the
level being broken would include the bar doing the breaking.

A useful habit: for each signal, ask what you would have known at the
moment of the trade, and check that every value in the condition was
fixed by then.

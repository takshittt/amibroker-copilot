---
title: Stops with ApplyStop
tags: [stops, applystop, backtest]
---
ApplyStop switches on one of the backtester's own stops. You say what
kind of stop it is, how the amount is measured, and the amount.

```afl
SetTradeDelays(1, 1, 1, 1);
Buy = Cross(Close, MA(Close, 50));
Sell = Cross(MA(Close, 50), Close);
ApplyStop(stopTypeLoss, stopModePercent, 3, True);
ApplyStop(stopTypeProfit, stopModePercent, 9, True);
```

The kinds are a maximum loss (stopTypeLoss), a profit target
(stopTypeProfit), a trailing stop (stopTypeTrailing) and an exit after a
number of bars (stopTypeNBar). The amount is read as a percentage
(stopModePercent), as points of price (stopModePoint) or as bars
(stopModeBars).

A stop sized by volatility uses points, with ATR as the amount:

```afl
ApplyStop(stopTypeTrailing, stopModePoint, 2 * ATR(14), True, True);
```

The fourth argument says whether the trade leaves at the stop level
inside the bar (True) or at the bar's normal trade price. The fifth
lets the amount change from bar to bar, which a trailing stop that
follows ATR needs.

These stops act inside the backtester. They do not appear in the Sell
array, so a chart drawn from Sell will not show them. Each kind of stop
can be set once; a second ApplyStop of the same kind replaces the first.

If you write a stop by hand instead, by comparing Low with a level, set
SellPrice to that level, or the backtest will not exit at the stop.

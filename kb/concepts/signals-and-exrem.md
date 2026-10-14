---
title: Buy, Sell, Short and Cover, and cleaning them with ExRem
tags: [signals, exrem, backtest]
---
A strategy tells the backtester what to do through four arrays. Buy and
Sell open and close long trades. Short and Cover open and close short
trades. A bar where the array is true is a signal.

```afl
SetTradeDelays(1, 1, 1, 1);
Fast = EMA(Close, 9);
Slow = EMA(Close, 21);
Buy = Cross(Fast, Slow);
Sell = Cross(Slow, Fast);
BuyPrice = Open;
SellPrice = Open;
```

Cross gives a signal on one bar only: the bar where the first line moves
above the second. A condition such as `Close > Slow` is different. It
stays true on every bar above the average, so it repeats.

The backtester ignores a repeated Buy while a trade is already open, so
results are not affected. A chart is: PlotShapes would draw an arrow on
every one of those bars. ExRem removes the repeats, keeping the first
signal until the opposite one arrives.

```afl
Buy = Close > MA(Close, 20);
Sell = Close < MA(Close, 20);
Buy = ExRem(Buy, Sell);
Sell = ExRem(Sell, Buy);
PlotShapes(Buy * shapeUpArrow, colorGreen, 0, Low);
PlotShapes(Sell * shapeDownArrow, colorRed, 0, High);
```

A long-only strategy needs only Buy and Sell. If the code never assigns
Short and Cover, no short trades are taken.

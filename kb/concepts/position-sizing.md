---
title: Position sizing with SetPositionSize
tags: [sizing, backtest]
---
SetPositionSize sets how big each new trade is. The second argument
says what the first one means.

```afl
SetPositionSize(10, spsPercentOfEquity);
```

- spsShares: a number of shares or contracts.
- spsValue: an amount of money.
- spsPercentOfEquity: a percentage of the account's current value.

The size can be an array, so it can differ from trade to trade. Sizing
by risk makes each trade lose about the same share of the account if
its stop is hit: a wider stop gives a smaller position.

```afl
RiskPercent = Param("Risk per trade %", 1, 0.25, 5, 0.25);
StopDistance = 2 * ATR(14);
SetPositionSize(RiskPercent * Close / StopDistance, spsPercentOfEquity);
ApplyStop(stopTypeLoss, stopModePoint, StopDistance, True);
```

Here the position's share of equity is the risk percentage multiplied by
price and divided by the stop distance.

For futures, one contract is `SetPositionSize(1, spsShares)`. The lot
size and margin come from the symbol's settings in AmiBroker, not from
the formula, so they must be set there for the money figures to be
right.

How many trades can be open together is a separate setting, made with
SetOption and "MaxOpenPositions".

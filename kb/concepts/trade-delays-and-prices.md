---
title: Trade delays and trade prices must agree
tags: [backtest, trade-delays, prices]
---
Two settings decide when and at what price the backtester fills a
signal, and they have to make sense together.

SetTradeDelays says how many bars after the signal each kind of trade
happens: buy, sell, short and cover, in that order. BuyPrice, SellPrice,
ShortPrice and CoverPrice say which price of that bar is used.

A signal worked out from a bar's close is only known once that bar has
finished. The usual honest choices are:

```afl
SetTradeDelays(1, 1, 1, 1);
Buy = Cross(Close, MA(Close, 20));
Sell = Cross(MA(Close, 20), Close);
BuyPrice = Open;
SellPrice = Open;
```

which trades at the open of the next bar, or a delay of 0 with the
price set to Close, which trades at the close of the signal bar.

A delay of 0 with the price set to Open is a mistake when the signal
uses that same bar's close: the trade is filled at a price from before
the signal existed. It is correct only when the signal is built
entirely from earlier bars, with Ref and a negative number.

Always call SetTradeDelays in the formula. Without it the backtester
uses the delays in its Settings window, and the same code gives
different results on different computers.

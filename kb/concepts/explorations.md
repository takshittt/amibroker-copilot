---
title: Explorations list the symbols that meet a condition
tags: [exploration, scan]
---
An exploration runs a formula over many symbols and shows a table of
the bars that pass. It takes no trades. It is how you scan a watch list
for setups.

Filter decides which bars are listed. AddColumn adds a number to the
table and AddTextColumn adds text.

```afl
Trend = ADX(14);
Momentum = RSI(14);
NearHigh = Close > 0.95 * HHV(High, 250);

Filter = Trend > 25 AND Momentum > 55 AND NearHigh;

AddTextColumn(FullName(), "Name");
AddColumn(Close, "Close");
AddColumn(Trend, "ADX");
AddColumn(Momentum, "RSI");
AddColumn(Volume, "Volume", 1.0);
SetSortColumns(-4);
```

The third argument of AddColumn sets the number format: 1.2 shows two
decimals and 1.0 shows none. SetSortColumns sorts the table; a negative
number sorts that column from high to low.

With the range set to the last bar, the table shows the symbols that
qualify today. `Filter = 1` lists every symbol, which is useful for
simply viewing values.

A formula can hold both an exploration and a strategy. If Filter is
built from Buy, clean Buy with ExRem first, or the symbol is listed on
every bar the condition holds.

---
title: AFL works on whole arrays, not one bar at a time
tags: [arrays, basics]
---
In AFL a name such as Close does not hold one price. It holds every
bar's price at once, and an expression is worked out for all bars in a
single step. `Close > Open` is therefore not one true or false; it is a
true or false for each bar.

This is why most AFL has no loops. You describe the calculation once and
AmiBroker applies it to every bar.

```afl
Avg = MA(Close, 20);
AboveAvg = Close > Avg;
Rising = Close > Ref(Close, -1);
Strong = AboveAvg AND Rising;
```

Each line gives a new array. `Strong` is true on the bars where both
conditions hold.

A loop is only needed when a bar's value depends on a value the same
calculation produced on an earlier bar, as in a hand-written trailing
stop. Most strategies never need one.

Two consequences catch people out. An `if` statement needs a single
true or false, so it cannot take an array; use IIf to choose bar by
bar. And to read an earlier bar you use Ref with a negative number, not
an index.

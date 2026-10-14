import Link from "next/link";
import { AnswerView } from "@/components/Answer";
import { checkName } from "@/lib/answer";
import { CHECKED, EXAMPLE_REQUEST } from "@/lib/fixtures";
import styles from "./landing.module.css";

const CHECKS = [
  "unknown_function",
  "arg_count",
  "lookahead_ref",
  "if_on_array",
  "eod_exit",
  "intrabar_stop_price",
  "trade_delays",
  "exrem",
  "hardcoded_times",
  "syntax",
];

export default function Landing() {
  return (
    <div className={styles.page}>
      <header className={styles.masthead}>
        <Link href="/" className={styles.wordmark}>
          AFL Copilot
        </Link>
        <nav className={styles.nav} aria-label="Account">
          <Link href="/login">Log in</Link>
          <Link href="/signup" className={styles.primary}>
            Create an account
          </Link>
        </nav>
      </header>

      <main>
        <section className={styles.hero}>
          <div className={styles.pitch}>
            <h1>AmiBroker code you can check before you paste it.</h1>
            <p className={styles.lead}>
              Describe a strategy in plain English. AFL Copilot writes the AFL, then a checker that
              knows every AmiBroker function reads it line by line. You see what passed, and
              anything it could not check is marked in red.
            </p>
            <div className={styles.ctas}>
              <Link href="/signup" className={styles.primary}>
                Create an account
              </Link>
              <Link href="/login">Log in</Link>
            </div>
          </div>

          <div className={styles.specimen}>
            <p className={styles.request}>
              <span className={styles.requestLabel}>Asked for</span>
              {EXAMPLE_REQUEST}
            </p>
            <AnswerView answer={{ ...CHECKED, notes: [] }} />
          </div>
        </section>

        <section className={styles.checks} aria-labelledby="checks-title">
          <h2 id="checks-title">The mistakes that quietly ruin a backtest</h2>
          <p>
            General chatbots write AFL that does not compile, or worse, compiles and gives results
            that could never be traded. Every answer here is checked for these before you see it:
          </p>
          <ul className={styles.checkList}>
            {CHECKS.map((rule) => (
              <li key={rule}>{checkName(rule)}</li>
            ))}
          </ul>
          <p>
            The checker is fixed rules, not AI. When code still fails after three attempts, you get
            it with the failures listed, never labelled as checked.
          </p>
        </section>

        <section className={styles.modes} aria-labelledby="modes-title">
          <h2 id="modes-title">Three ways to use it</h2>
          <dl>
            <div>
              <dt>Write</dt>
              <dd>
                Pick your market and timeframe, describe the strategy, and get checked code with
                each block explained and the session times as parameters.
              </dd>
            </div>
            <div>
              <dt>Review</dt>
              <dd>
                Paste your own AFL. Findings from the checker are kept apart from the AI&apos;s
                suggestions, so you know which ones are certain. One click applies the fixes.
              </dd>
            </div>
            <div>
              <dt>Fix an error</dt>
              <dd>
                Paste the code and the error AmiBroker showed. You get corrected code, checked
                again.
              </dd>
            </div>
          </dl>
        </section>

        <section className={styles.limits} aria-labelledby="limits-title">
          <h2 id="limits-title">What it does not do</h2>
          <p>
            AFL Copilot writes and checks code. It does not run backtests, place trades, or tell you
            what to trade, and nothing here is financial advice. Always backtest a strategy yourself
            in AmiBroker before you trade it.
          </p>
        </section>
      </main>

      <footer className={styles.footer}>
        <p>
          AFL Copilot is not made by or connected to AmiBroker. Links go to AmiBroker&apos;s own
          documentation.
        </p>
      </footer>
    </div>
  );
}

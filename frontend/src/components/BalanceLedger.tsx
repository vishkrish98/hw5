import { useEffect, useRef, useState } from "react";

export interface ApprovedPayment {
  kind: "invoice" | "lease";
  refId: number;
  amount: number;
}

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
}

export function BalanceLedger({
  balance,
  startingBalance,
  payments,
}: {
  balance: number | null;
  startingBalance: number | null;
  payments: ApprovedPayment[];
}) {
  const [flash, setFlash] = useState(false);
  const prev = useRef<number | null>(null);

  useEffect(() => {
    if (balance === null) return;
    if (prev.current !== null && balance !== prev.current) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 700);
      prev.current = balance;
      return () => clearTimeout(t);
    }
    prev.current = balance;
  }, [balance]);

  return (
    <div>
      <div className="panel-title small-caps">The ledger</div>
      <div className={`balance-figure tabular${flash ? " flash" : ""}`}>
        {balance === null ? "—" : money(balance)}
      </div>
      <div className="balance-label small-caps">checking balance</div>

      <div className="balance-strip">
        <div className="balance-strip-row">
          <span>Starting</span>
          <b className="tabular">{startingBalance === null ? "—" : money(startingBalance)}</b>
        </div>
        {payments.map((p, i) => (
          <div className="balance-strip-row drop" key={i}>
            <span>
              Paid {p.kind} #{p.refId}
            </span>
            <b className="tabular">-{money(p.amount)}</b>
          </div>
        ))}
        <div className="balance-strip-row current">
          <span>Current</span>
          <b className="tabular">{balance === null ? "—" : money(balance)}</b>
        </div>
      </div>
    </div>
  );
}

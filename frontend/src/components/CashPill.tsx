import { useEffect, useRef, useState } from "react";

export function CashPill({ balance }: { balance: number | null }) {
  const [flash, setFlash] = useState(false);
  const [dropped, setDropped] = useState(false);
  const prev = useRef<number | null>(null);

  useEffect(() => {
    if (balance === null) return;
    if (prev.current !== null && balance !== prev.current) {
      setDropped(balance < prev.current);
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 600);
      prev.current = balance;
      return () => clearTimeout(t);
    }
    prev.current = balance;
  }, [balance]);

  return (
    <div className={`cash-pill${dropped ? " dropped" : ""}`}>
      <span className="dot" />
      <span className={`amount${flash ? " flash" : ""}`}>
        {balance === null ? "—" : `$${balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
      </span>
    </div>
  );
}

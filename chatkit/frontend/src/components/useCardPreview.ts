import { useEffect, useRef, useState } from "react";

export function useCardPreview<Card>() {
  const tooltip = useRef<HTMLDivElement>(null);
  const pending = useRef<{ timer: number; element: HTMLButtonElement; x: number; y: number } | null>(null);
  const [card, setCard] = useState<Card | null>(null);

  function clearPending() {
    if (!pending.current) return;
    window.clearTimeout(pending.current.timer);
    pending.current.element.classList.remove("is-preview-pending");
    pending.current = null;
  }
  function hide() {
    clearPending();
    if (tooltip.current?.matches(":popover-open")) tooltip.current.hidePopover();
    setCard(null);
  }
  function place(element: HTMLButtonElement, x: number, y: number) {
    const popup = tooltip.current;
    if (!popup?.matches(":popover-open")) return;
    const bounds = popup.getBoundingClientRect();
    const target = element.getBoundingClientRect();
    const clamp = (value: number, max: number) => Math.max(8, Math.min(value, max));
    const maxLeft = window.innerWidth - bounds.width - 8;
    const maxTop = window.innerHeight - bounds.height - 8;
    const top = clamp(y + 24, maxTop);
    const right = Math.max(x + 36, target.right + 36);
    const left = Math.min(x - bounds.width - 36, target.left - bounds.width - 36);
    const candidates = [
      [right, top], [left, top],
      [clamp(x + 36, maxLeft), target.bottom + 16],
      [clamp(x + 36, maxLeft), target.top - bounds.height - 16],
    ].filter(([candidateLeft, candidateTop]) => candidateLeft >= 8 && candidateLeft <= maxLeft && candidateTop >= 8 && candidateTop <= maxTop);
    const overlap = ([candidateLeft, candidateTop]: number[]) =>
      Math.max(0, Math.min(candidateLeft + bounds.width, target.right + 12) - Math.max(candidateLeft, target.left - 12))
      * Math.max(0, Math.min(candidateTop + bounds.height, target.bottom + 12) - Math.max(candidateTop, target.top - 12));
    const [placedLeft, placedTop] = candidates.find(candidate => overlap(candidate) === 0)
      ?? candidates.reduce((best, candidate) => overlap(candidate) < overlap(best) ? candidate : best, [clamp(right, maxLeft), top]);
    popup.style.left = `${placedLeft}px`;
    popup.style.top = `${placedTop}px`;
  }
  function show(next: Card, element: HTMLButtonElement, x: number, y: number) {
    clearPending();
    setCard(next);
    if (!tooltip.current) return;
    if (!tooltip.current.matches(":popover-open")) tooltip.current.showPopover();
    place(element, x, y);
  }
  function queue(next: Card, element: HTMLButtonElement, x: number, y: number) {
    hide();
    element.classList.add("is-preview-pending");
    const queued = { timer: 0, element, x, y };
    queued.timer = window.setTimeout(() => {
      if (pending.current === queued) show(next, element, queued.x, queued.y);
    }, 380);
    pending.current = queued;
  }
  function move(element: HTMLButtonElement, x: number, y: number) {
    if (pending.current?.element === element) { pending.current.x = x; pending.current.y = y; }
  }
  useEffect(() => () => {
    if (pending.current) {
      window.clearTimeout(pending.current.timer);
      pending.current.element.classList.remove("is-preview-pending");
    }
    if (tooltip.current?.matches(":popover-open")) tooltip.current.hidePopover();
  }, []);
  return { tooltip, card, show, queue, move, hide };
}

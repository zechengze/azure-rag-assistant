import { useCallback, useEffect, useState } from "react";

/** 與 Tailwind `md` 斷點一致 —— 達到此寬度即改用常駐側欄,抽屜不再存在。 */
const DESKTOP_QUERY = "(min-width: 768px)";

interface UseNavDrawerReturn {
  isOpen: boolean;
  /** 是否已達常駐側欄寬度。抽屜的 inert / dialog 語意只在非桌面版成立,故需暴露。 */
  isDesktop: boolean;
  open: () => void;
  close: () => void;
}

/**
 * 手機版知識庫抽屜的開關狀態。
 *
 * 開啟期間鎖住背景捲動並支援 Esc 關閉;放大到桌面版 (≥md) 時強制關閉,
 * 避免捲動鎖與背景 inert 殘留在已經變成常駐側欄的佈局上。
 */
export function useNavDrawer(): UseNavDrawerReturn {
  const [isOpen, setIsOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(
    () => window.matchMedia(DESKTOP_QUERY).matches,
  );

  const open = useCallback((): void => setIsOpen(true), []);
  const close = useCallback((): void => setIsOpen(false), []);

  useEffect(() => {
    const query = window.matchMedia(DESKTOP_QUERY);
    // resize 一併監聽:change 事件在部分嵌入式 / 受控 viewport 下不會送達,
    // 兩者都綁可確保跨越斷點時 isDesktop 不會停在舊值。
    const sync = (): void => {
      setIsDesktop(query.matches);
      if (query.matches) {
        setIsOpen(false);
      }
    };
    query.addEventListener("change", sync);
    window.addEventListener("resize", sync);
    return () => {
      query.removeEventListener("change", sync);
      window.removeEventListener("resize", sync);
    };
  }, []);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  return { isOpen, isDesktop, open, close };
}

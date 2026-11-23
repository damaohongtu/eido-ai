import React, { useEffect, useRef } from 'react';

const paths = {
  menu: 'M4 6h16M4 12h16M4 18h16',
  plus: 'M12 5v14M5 12h14',
  home: 'm3 10 9-7 9 7v10H6V10m3 10v-7h6v7',
  spark: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z',
  tools: 'm14 7 3 3m-9 5-4 5 2 2 5-4m1-10a6 6 0 0 0 7 7l4-4-4-1-1-4-4 4Z',
  clock: 'M12 8v5l3 2m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  close: 'm6 6 12 12M6 18 18 6',
  back: 'm14 5-7 7 7 7',
  send: 'M12 19V5m-6 6 6-6 6 6',
  file: 'M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 12h8M8 16h5',
  folder: 'M3 7V4h6l3 3h9v13H3V7Z',
  chat: 'M21 4H3v14h5l4 3v-3h9V4Z',
  attach: 'm8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l8-8',
  settings: 'M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6m-6 0v6',
};

export function Icon({
  name,
  size = 22,
}: {
  name: keyof typeof paths;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

export function Sheet({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => {
      dialog.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="h5-sheet"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <header>
        <h2>{title}</h2>
        <button
          type="button"
          className="h5-icon-button"
          aria-label="关闭"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </header>
      <div className="h5-sheet-body">{children}</div>
    </dialog>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="h5-empty">
      <Icon name="spark" size={32} />
      <p>{children}</p>
    </div>
  );
}

export function Drawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="h5-drawer"
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < bounds.left ||
          event.clientX > bounds.right ||
          event.clientY < bounds.top ||
          event.clientY > bounds.bottom
        )
          onClose();
      }}
    >
      <button
        type="button"
        className="h5-icon-button h5-drawer-close"
        aria-label="关闭抽屉"
        onClick={onClose}
      >
        <Icon name="close" />
      </button>
      {children}
    </dialog>
  );
}

export function ErrorMessage({ error }: { error: string }) {
  return error ? (
    <p className="h5-error" role="alert">
      {error}
    </p>
  ) : null;
}

export function errorText(error: unknown) {
  return error instanceof Error ? error.message : '操作失败，请重试';
}

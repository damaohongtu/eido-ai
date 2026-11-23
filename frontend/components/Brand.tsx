import React from 'react';

/** Shared PC/H5 identity; independent of legacy public image files and caches. */
export default function Brand() {
  return (
    <span
      className="eido-brand inline-flex items-center gap-2"
      aria-label="Eido"
    >
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gray-600 text-lg font-bold text-white">
        E
      </span>
      <span className="text-xl font-bold tracking-tight text-gray-900">
        ido
      </span>
    </span>
  );
}

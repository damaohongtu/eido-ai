import React, { useEffect, useState } from 'react';
import { BACKEND_URL } from '../constants';
import { api, type LoginProvider } from '../services/api';

export default function LoginView() {
  const [providers, setProviders] = useState<LoginProvider[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api.listLoginProviders().then(items => {
      if (!active) return;
      if (items.length === 1 && items[0].id === 'dev') {
        window.location.href = `${BACKEND_URL}/api/v1/auth/login`;
        return;
      }
      setProviders(items);
    }).catch(err => {
      if (!active) return;
      setError(err.message);
      setProviders([{ id: 'cas', name: 'CAS' }]);
    });
    return () => { active = false; };
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-6">
      <div className="w-full max-w-sm rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
        <h1 className="text-3xl font-semibold tracking-tight text-gray-900">Eido</h1>
        <p className="mt-2 text-sm text-gray-500">登录以继续你的工作</p>
        <div className="mt-8 space-y-3">
          {providers.map(provider => (
            <a
              key={provider.id}
              href={`${BACKEND_URL}/api/v1/auth/login${provider.id === 'cas' ? '' : `/${provider.id}`}`}
              className="flex w-full items-center justify-center rounded-lg border border-gray-300 px-4 py-3 text-sm font-medium text-gray-800 transition hover:border-gray-500 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2"
            >
              使用 {provider.name} 登录
            </a>
          ))}
          {!providers.length && <p className="text-sm text-gray-500" role="status">正在加载登录方式...</p>}
        </div>
        {error && (
          <div className="mt-5 text-sm text-red-600" role="alert">
            <p>{error}</p>
            <button className="mt-2 underline" onClick={() => window.location.reload()}>重新加载</button>
          </div>
        )}
      </div>
    </main>
  );
}

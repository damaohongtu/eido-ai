import React from 'react';

/** 汉堡菜单图标，用作各页面 NavBar 左侧（点击打开抽屉）。 */
const MenuIcon: React.FC = () => (
  <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
  </svg>
);

export default MenuIcon;

import React from 'react';
import MenuItem from '../components/MenuItem';
import menuData from '../data/menu.json';

const Menu = () => {
  return (
    <div className="menu-page">
      <h1>Our Menu</h1>
      <div className="menu-items">
        {menuData.map(item => (
          <MenuItem key={item.id} {...item} />
        ))}
      </div>
    </div>
  );
};

export default Menu;
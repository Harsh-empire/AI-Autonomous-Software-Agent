import React from 'react';
import menuItems from '../../assets/menu-items.json';
import './Menu.css';

const Menu = () => {
  return (
    <div className="menu-container">
      <h1>Our Menu</h1>
      <div className="menu-items">
        {menuItems.map(item => (
          <div key={item.id} className="menu-item">
            <img src={item.image} alt={item.name} />
            <h2>{item.name}</h2>
            <p>{item.description}</p>
            <p>${item.price}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

export default Menu;
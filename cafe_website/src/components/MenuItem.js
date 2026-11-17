import React from 'react';
import { Link } from 'react-router-dom';
import './MenuItem.css';

const MenuItem = ({ item }) => {
  return (
    <div className="menu-item">
      <img src={item.image} alt={item.name} />
      <h3>{item.name}</h3>
      <p>{item.description}</p>
      <p>${item.price}</p>
      <Link to={`/menu/${item.id}`}>View Details</Link>
    </div>
  );
};

export default MenuItem;
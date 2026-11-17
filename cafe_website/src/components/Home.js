import React from 'react';
import './Home.css';

const Home = () => {
  return (
    <div className="home-container">
      <h1>Welcome to Our Cafe</h1>
      <p>We serve delicious food and drinks in a cozy atmosphere.</p>
      <h2>Our Menu</h2>
      <ul>
        <li><a href="/menu">View Menu</a></li>
      </ul>
    </div>
  );
};

export default Home;
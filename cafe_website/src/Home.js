import React from 'react';
import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import Footer from '../components/Footer';
import './Home.css';

const Home = () => {
  return (
    <div className="home-container">
      <Navbar />
      <div className="hero-section">
        <h1>Welcome to Our Cafe</h1>
        <p>Enjoy delicious food and drinks in a cozy atmosphere.</p>
        <Link to="/menu" className="cta-button">View Menu</Link>
      </div>
      <Footer />
    </div>
  );
};

export default Home;
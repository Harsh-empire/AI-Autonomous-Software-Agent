import React from 'react';
import { Link } from 'react-router-dom';
import './Footer.css';

const Footer = () => {
  return (
    <footer className="footer">
      <div className="footer-content">
        <div className="footer-left">
          <h3>Cafe Name</h3>
          <p>123 Cafe Street, City, Country</p>
          <p>Phone: +1234567890</p>
          <p>Email: info@cafe.com</p>
        </div>
        <div className="footer-right">
          <h3>Quick Links</h3>
          <ul>
            <li><Link to="/">Home</Link></li>
            <li><Link to="/menu">Menu</Link></li>
            <li><Link to="/reservations">Reservations</Link></li>
            <li><Link to="/contact">Contact</Link></li>
          </ul>
        </div>
      </div>
      <div className="footer-bottom">
        <p>&copy; {new Date().getFullYear()} Cafe Name. All rights reserved.</p>
      </div>
    </footer>
  );
};

export default Footer;
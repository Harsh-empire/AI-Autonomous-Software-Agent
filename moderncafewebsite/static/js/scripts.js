document.addEventListener('DOMContentLoaded', function() {
    // Add event listeners for cart functionality
    document.querySelectorAll('.add-to-cart').forEach(button => {
        button.addEventListener('click', function() {
            const itemId = this.getAttribute('data-item-id');
            fetch(`/add_to_cart/${itemId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Item added to cart!');
                    updateCartCount(data.cart_count);
                } else {
                    alert('Failed to add item to cart.');
                }
            });
        });
    });

    // Function to update cart count in the UI
    function updateCartCount(count) {
        const cartCountElement = document.getElementById('cart-count');
        if (cartCountElement) {
            cartCountElement.textContent = count;
        }
    }

    // Add event listener for checkout button
    document.getElementById('checkout-button').addEventListener('click', function() {
        window.location.href = '/checkout';
    });
});
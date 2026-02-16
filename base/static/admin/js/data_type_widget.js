(function() {
    'use strict';

    // Wait for DOM to be ready
    document.addEventListener('DOMContentLoaded', function() {
        // Find all data type checkbox lists
        var checkboxLists = document.querySelectorAll('.data-type-checkbox-list');

        checkboxLists.forEach(function(list) {
            // Add custom class for styling
            list.classList.add('enhanced-data-type-list');

            // Add toggle all functionality
            addToggleAllButton(list);

            // Add live count of excluded items
            updateExcludedCount(list);

            // Listen for checkbox changes
            list.addEventListener('change', function() {
                updateExcludedCount(list);
            });
        });
    });

    function addToggleAllButton(list) {
        var container = list.parentElement;
        var buttonContainer = document.createElement('div');
        buttonContainer.style.marginBottom = '10px';

        var toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.textContent = 'Toggle All';
        toggleBtn.className = 'button';
        toggleBtn.style.marginRight = '10px';

        toggleBtn.addEventListener('click', function() {
            var checkboxes = list.querySelectorAll('input[type="checkbox"]');
            var allChecked = Array.from(checkboxes).every(cb => cb.checked);

            checkboxes.forEach(function(checkbox) {
                checkbox.checked = !allChecked;
            });

            updateExcludedCount(list);
        });

        var selectNoneBtn = document.createElement('button');
        selectNoneBtn.type = 'button';
        selectNoneBtn.textContent = 'Include All';
        selectNoneBtn.className = 'button';
        selectNoneBtn.style.marginRight = '10px';

        selectNoneBtn.addEventListener('click', function() {
            var checkboxes = list.querySelectorAll('input[type="checkbox"]');
            checkboxes.forEach(function(checkbox) {
                checkbox.checked = false;
            });
            updateExcludedCount(list);
        });

        buttonContainer.appendChild(toggleBtn);
        buttonContainer.appendChild(selectNoneBtn);
        container.insertBefore(buttonContainer, list);
    }

    function updateExcludedCount(list) {
        var checkboxes = list.querySelectorAll('input[type="checkbox"]');
        var total = checkboxes.length;
        var excluded = Array.from(checkboxes).filter(cb => cb.checked).length;
        var included = total - excluded;

        var countDisplay = list.parentElement.querySelector('.excluded-count');

        if (!countDisplay) {
            countDisplay = document.createElement('div');
            countDisplay.className = 'excluded-count';
            countDisplay.style.cssText = 'padding: 10px; background: #f0f7fa; border-left: 4px solid #417690; margin: 10px 0; border-radius: 4px;';
            list.parentElement.insertBefore(countDisplay, list);
        }

        countDisplay.innerHTML = '<strong>Status:</strong> ' +
            '<span style="color: #28a745;">' + included + ' included</span> | ' +
            '<span style="color: #ffc107;">' + excluded + ' excluded</span> | ' +
            '<span style="color: #666;">' + total + ' total</span>';
    }
})();

import React from 'react';

const MedicationIcon = ({ iconSvg, medicationColor, backgroundColor, size = 24 }) => {
  return (
    <div 
      className="medication-icon-container"
      style={{
        width: size * 2,
        height: size * 2,
        borderRadius: '50%',
        backgroundColor: backgroundColor,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
      }}
    >
      <img 
        src={iconSvg} 
        alt="medication"
        style={{
          width: size,
          height: size,
          filter: getColorFilter(medicationColor)
        }}
      />
    </div>
  );
};

// Helper function to convert hex color to CSS filter
const getColorFilter = (hexColor) => {
  // For white or very light colors, invert to make them visible
  if (hexColor === '#FFFFFF' || hexColor === '#F8FAFC') {
    return 'brightness(0) saturate(100%) invert(1)';
  }
  // For other colors, keep them as is
  return 'brightness(0) saturate(100%)';
};

export default MedicationIcon;

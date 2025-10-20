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
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
        border: '2px solid rgba(255,255,255,0.3)'
      }}
    >
      <img 
        src={iconSvg} 
        alt="medication"
        style={{
          width: size,
          height: size,
          display: 'block'
        }}
      />
    </div>
  );
};

export default MedicationIcon;

import React from "react";

const HEX6 = /^#(?:[0-9a-fA-F]{6})$/;
const HEX8 = /^#(?:[0-9a-fA-F]{8})$/;
const DEFAULT_BG = "#E2E8F0";
const DEFAULT_PILL = "#0EA5E9";

const validateHex = (value, fallback) => {
  if (value && (HEX6.test(value) || HEX8.test(value))) {
    return value;
  }
  return fallback;
};

const MedicationIcon = ({ iconSvg, medicationColor, backgroundColor, size = 24 }) => {
  const bgColor = validateHex(backgroundColor, DEFAULT_BG);
  const pillColor = validateHex(medicationColor, DEFAULT_PILL);
  const innerSize = size * 1.2;

  const renderInlineSvg = () => {
    if (!iconSvg) {
      return (
        <span
          style={{
            width: innerSize * 0.6,
            height: innerSize * 0.6,
            borderRadius: 12,
            backgroundColor: pillColor,
            display: "inline-block",
          }}
        />
      );
    }

    const trimmed = iconSvg.trim();
    if (trimmed.startsWith("<svg")) {
      return (
        <span
          aria-hidden="true"
          dangerouslySetInnerHTML={{ __html: trimmed }}
          style={{
            display: "inline-flex",
            width: innerSize,
            height: innerSize,
          }}
        />
      );
    }

    return (
      <img
        src={iconSvg}
        alt="medication icon"
        style={{
          width: innerSize,
          height: innerSize,
          display: "block",
        }}
      />
    );
  };

  return (
    <div
      className="medication-icon-container"
      style={{
        width: size * 2,
        height: size * 2,
        borderRadius: "50%",
        backgroundColor: bgColor,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
        border: "2px solid rgba(255,255,255,0.3)",
      }}
    >
      {renderInlineSvg()}
    </div>
  );
};

export default MedicationIcon;

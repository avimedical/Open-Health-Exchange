# FHIR Device Examples - Comprehensive Guide

## Overview

This document provides comprehensive FHIR R5 examples for the major device types supported by Open Health Exchange. Each example includes realistic device data, proper FHIR resource structures, and demonstrates the complete data transformation pipeline.

## Table of Contents

1. [SmartWatch (Withings ScanWatch 2)](#smartwatch-withings-scanwatch-2)
2. [Smart Scale (Withings Body+)](#smart-scale-withings-body)
3. [Blood Pressure Monitor (Withings BPM Connect)](#blood-pressure-monitor-withings-bpm-connect)
4. [Pulse Oximeter (Fitbit Sense 2)](#pulse-oximeter-fitbit-sense-2)

---

## SmartWatch (Withings ScanWatch 2)

### Device Resource

```json
{
  "resourceType": "Device",
  "id": "withings-scanwatch2-987654321",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.withings.com/device-id",
      "value": "987654321",
      "assigner": {
        "display": "Withings Health Platform"
      }
    },
    {
      "use": "secondary",
      "system": "https://open-health-exchange.org/device",
      "value": "withings-scanwatch2-987654321"
    }
  ],
  "displayName": "John's ScanWatch 2",
  "type": [
    {
      "coding": [
        {
          "system": "http://snomed.info/sct",
          "code": "706767009",
          "display": "Wearable device"
        }
      ],
      "text": "Smartwatch"
    }
  ],
  "manufacturer": "Withings",
  "modelNumber": "ScanWatch 2 - 42mm",
  "serialNumber": "SW2-42-987654321",
  "version": [
    {
      "type": {
        "coding": [
          {
            "system": "http://terminology.hl7.org/CodeSystem/device-version-type",
            "code": "firmware-version"
          }
        ]
      },
      "value": "2.4.1"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://terminology.hl7.org/CodeSystem/device-version-type",
            "code": "hardware-version"
          }
        ]
      },
      "value": "Gen2"
    }
  ],
  "capability": [
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "8867-4",
            "display": "Heart rate"
          }
        ]
      },
      "description": "Continuous heart rate monitoring"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "131328-5",
            "display": "Electrocardiogram"
          }
        ]
      },
      "description": "Single-lead ECG recording"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "55423-8",
            "display": "Number of steps"
          }
        ]
      },
      "description": "Step counting and activity tracking"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "93832-4",
            "display": "Sleep study"
          }
        ]
      },
      "description": "Sleep phase detection and analysis"
    }
  ],
  "property": [
    {
      "type": {
        "coding": [
          {
            "system": "http://terminology.hl7.org/CodeSystem/device-property-type",
            "code": "battery-level",
            "display": "Battery Level"
          }
        ]
      },
      "valueQuantity": {
        "value": 78,
        "unit": "%",
        "system": "http://unitsofmeasure.org",
        "code": "%"
      }
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "lastSyncTime",
            "display": "Last Sync Time"
          }
        ]
      },
      "valueDateTime": "2023-12-07T08:15:30Z"
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "wearLocation",
            "display": "Wear Location"
          }
        ]
      },
      "valueString": "left-wrist"
    }
  ],
  "safety": [
    {
      "coding": [
        {
          "system": "urn:oid:2.16.840.1.113883.3.26.1.1",
          "code": "mr-conditional",
          "display": "MR Conditional"
        }
      ]
    }
  ],
  "note": [
    {
      "time": "2023-12-07T08:15:30Z",
      "text": "Device paired with Withings Health Mate app. ECG feature activated. Water resistant up to 50m."
    }
  ]
}
```

### Heart Rate Observation

```json
{
  "resourceType": "Observation",
  "id": "smartwatch-hr-20231207081530",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.withings.com/measurement-id",
      "value": "hr-measurement-456789123"
    }
  ],
  "status": "final",
  "category": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/observation-category",
          "code": "vital-signs",
          "display": "Vital Signs"
        }
      ]
    }
  ],
  "code": {
    "coding": [
      {
        "system": "http://loinc.org",
        "code": "8867-4",
        "display": "Heart rate"
      }
    ],
    "text": "Heart rate"
  },
  "subject": {
    "reference": "Patient/patient-john-doe"
  },
  "effectiveDateTime": "2023-12-07T08:15:30Z",
  "valueQuantity": {
    "value": 68,
    "unit": "beats/min",
    "system": "http://unitsofmeasure.org",
    "code": "/min"
  },
  "device": {
    "reference": "Device/withings-scanwatch2-987654321"
  },
  "component": [
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "measurement-context",
            "display": "Measurement Context"
          }
        ]
      },
      "valueString": "resting"
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "measurement-quality",
            "display": "Measurement Quality"
          }
        ]
      },
      "valueString": "good"
    }
  ],
  "meta": {
    "tag": [
      {
        "system": "https://open-health-exchange.org/provider",
        "code": "withings",
        "display": "Withings"
      },
      {
        "system": "https://open-health-exchange.org/device-type",
        "code": "smartwatch",
        "display": "Smartwatch"
      }
    ],
    "source": "https://api.withings.com",
    "versionId": "1",
    "lastUpdated": "2023-12-07T08:16:00Z"
  }
}
```

### ECG DiagnosticReport

```json
{
  "resourceType": "DiagnosticReport",
  "id": "smartwatch-ecg-20231207081530",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.withings.com/ecg-id",
      "value": "ecg-recording-789456123"
    }
  ],
  "status": "final",
  "category": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
          "code": "CG",
          "display": "Cardiac Electrophysiology"
        }
      ]
    }
  ],
  "code": {
    "coding": [
      {
        "system": "http://loinc.org",
        "code": "131328-5",
        "display": "Electrocardiogram study"
      }
    ],
    "text": "Single-lead ECG"
  },
  "subject": {
    "reference": "Patient/patient-john-doe"
  },
  "effectiveDateTime": "2023-12-07T08:15:30Z",
  "issued": "2023-12-07T08:16:00Z",
  "performer": [
    {
      "reference": "Device/withings-scanwatch2-987654321"
    }
  ],
  "result": [
    {
      "reference": "Observation/smartwatch-hr-20231207081530"
    }
  ],
  "conclusion": "Normal sinus rhythm. Heart rate: 68 bpm. No arrhythmias detected.",
  "conclusionCode": [
    {
      "coding": [
        {
          "system": "http://snomed.info/sct",
          "code": "426783006",
          "display": "Normal sinus rhythm"
        }
      ]
    }
  ],
  "media": [
    {
      "comment": "30-second ECG waveform data",
      "link": {
        "contentType": "application/json",
        "title": "ECG Waveform Data",
        "creation": "2023-12-07T08:15:30Z"
      }
    }
  ]
}
```

---

## Smart Scale (Withings Body+)

### Device Resource

```json
{
  "resourceType": "Device",
  "id": "withings-bodyplus-123456789",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.withings.com/device-id",
      "value": "123456789",
      "assigner": {
        "display": "Withings Health Platform"
      }
    }
  ],
  "displayName": "Bathroom Scale",
  "type": [
    {
      "coding": [
        {
          "system": "http://snomed.info/sct",
          "code": "19892000",
          "display": "Scale"
        }
      ],
      "text": "Smart Body Scale"
    }
  ],
  "manufacturer": "Withings",
  "modelNumber": "Body+ (WBS05)",
  "serialNumber": "WBS05-123456789",
  "version": [
    {
      "type": {
        "coding": [
          {
            "system": "http://terminology.hl7.org/CodeSystem/device-version-type",
            "code": "firmware-version"
          }
        ]
      },
      "value": "1208.0"
    }
  ],
  "capability": [
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "29463-7",
            "display": "Body weight"
          }
        ]
      },
      "description": "Precision weight measurement"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "39156-5",
            "display": "Body mass index (BMI) [Ratio]"
          }
        ]
      },
      "description": "Automatic BMI calculation"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "41982-0",
            "display": "Percentage of body fat"
          }
        ]
      },
      "description": "Bioelectrical impedance analysis"
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/measurement-type",
            "code": "muscle-mass",
            "display": "Muscle Mass"
          }
        ]
      },
      "description": "Muscle mass measurement"
    }
  ],
  "property": [
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "lastSyncTime",
            "display": "Last Sync Time"
          }
        ]
      },
      "valueDateTime": "2023-12-07T07:30:15Z"
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "wifi-connected",
            "display": "WiFi Connected"
          }
        ]
      },
      "valueBoolean": true
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "max-users",
            "display": "Maximum Users"
          }
        ]
      },
      "valueInteger": 8
    }
  ],
  "note": [
    {
      "time": "2023-12-07T07:30:15Z",
      "text": "Wi-Fi connected scale with multi-user recognition. Supports weight tracking for up to 8 users."
    }
  ]
}
```

### Weight Measurement Bundle

```json
{
  "resourceType": "Bundle",
  "id": "scale-measurement-bundle-20231207073015",
  "type": "collection",
  "timestamp": "2023-12-07T07:30:15Z",
  "entry": [
    {
      "resource": {
        "resourceType": "Observation",
        "id": "weight-20231207073015",
        "identifier": [
          {
            "use": "official",
            "system": "https://api.withings.com/measurement-id",
            "value": "weight-measurement-321654987"
          }
        ],
        "status": "final",
        "category": [
          {
            "coding": [
              {
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "vital-signs",
                "display": "Vital Signs"
              }
            ]
          }
        ],
        "code": {
          "coding": [
            {
              "system": "http://loinc.org",
              "code": "29463-7",
              "display": "Body weight"
            }
          ],
          "text": "Body weight"
        },
        "subject": {
          "reference": "Patient/patient-john-doe"
        },
        "effectiveDateTime": "2023-12-07T07:30:15Z",
        "valueQuantity": {
          "value": 78.2,
          "unit": "kg",
          "system": "http://unitsofmeasure.org",
          "code": "kg"
        },
        "device": {
          "reference": "Device/withings-bodyplus-123456789"
        },
        "component": [
          {
            "code": {
              "coding": [
                {
                  "system": "https://open-health-exchange.org/CodeSystem/observation-component",
                  "code": "measurement-stability",
                  "display": "Measurement Stability"
                }
              ]
            },
            "valueString": "stable"
          }
        ]
      }
    },
    {
      "resource": {
        "resourceType": "Observation",
        "id": "bmi-20231207073015",
        "identifier": [
          {
            "use": "official",
            "system": "https://api.withings.com/measurement-id",
            "value": "bmi-measurement-321654988"
          }
        ],
        "status": "final",
        "category": [
          {
            "coding": [
              {
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "vital-signs",
                "display": "Vital Signs"
              }
            ]
          }
        ],
        "code": {
          "coding": [
            {
              "system": "http://loinc.org",
              "code": "39156-5",
              "display": "Body mass index (BMI) [Ratio]"
            }
          ],
          "text": "BMI"
        },
        "subject": {
          "reference": "Patient/patient-john-doe"
        },
        "effectiveDateTime": "2023-12-07T07:30:15Z",
        "valueQuantity": {
          "value": 22.8,
          "unit": "kg/m2",
          "system": "http://unitsofmeasure.org",
          "code": "kg/m2"
        },
        "device": {
          "reference": "Device/withings-bodyplus-123456789"
        },
        "derivedFrom": [
          {
            "reference": "Observation/weight-20231207073015"
          }
        ]
      }
    },
    {
      "resource": {
        "resourceType": "Observation",
        "id": "body-fat-20231207073015",
        "identifier": [
          {
            "use": "official",
            "system": "https://api.withings.com/measurement-id",
            "value": "bodyfat-measurement-321654989"
          }
        ],
        "status": "final",
        "category": [
          {
            "coding": [
              {
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "survey",
                "display": "Survey"
              }
            ]
          }
        ],
        "code": {
          "coding": [
            {
              "system": "http://loinc.org",
              "code": "41982-0",
              "display": "Percentage of body fat"
            }
          ],
          "text": "Body fat percentage"
        },
        "subject": {
          "reference": "Patient/patient-john-doe"
        },
        "effectiveDateTime": "2023-12-07T07:30:15Z",
        "valueQuantity": {
          "value": 14.2,
          "unit": "%",
          "system": "http://unitsofmeasure.org",
          "code": "%"
        },
        "device": {
          "reference": "Device/withings-bodyplus-123456789"
        },
        "method": {
          "coding": [
            {
              "system": "http://snomed.info/sct",
              "code": "702991000",
              "display": "Bioelectrical impedance analysis"
            }
          ]
        }
      }
    },
    {
      "resource": {
        "resourceType": "Observation",
        "id": "muscle-mass-20231207073015",
        "identifier": [
          {
            "use": "official",
            "system": "https://api.withings.com/measurement-id",
            "value": "muscle-measurement-321654990"
          }
        ],
        "status": "final",
        "category": [
          {
            "coding": [
              {
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "survey",
                "display": "Survey"
              }
            ]
          }
        ],
        "code": {
          "coding": [
            {
              "system": "https://open-health-exchange.org/CodeSystem/loinc-extensions",
              "code": "muscle-mass-kg",
              "display": "Muscle mass in kilograms"
            }
          ],
          "text": "Muscle mass"
        },
        "subject": {
          "reference": "Patient/patient-john-doe"
        },
        "effectiveDateTime": "2023-12-07T07:30:15Z",
        "valueQuantity": {
          "value": 58.4,
          "unit": "kg",
          "system": "http://unitsofmeasure.org",
          "code": "kg"
        },
        "device": {
          "reference": "Device/withings-bodyplus-123456789"
        },
        "method": {
          "coding": [
            {
              "system": "http://snomed.info/sct",
              "code": "702991000",
              "display": "Bioelectrical impedance analysis"
            }
          ]
        }
      }
    }
  ],
  "meta": {
    "tag": [
      {
        "system": "https://open-health-exchange.org/provider",
        "code": "withings",
        "display": "Withings"
      },
      {
        "system": "https://open-health-exchange.org/device-type",
        "code": "scale",
        "display": "Smart Scale"
      }
    ],
    "source": "https://api.withings.com"
  }
}
```

---

## Blood Pressure Monitor (Withings BPM Connect)

### Device Resource

```json
{
  "resourceType": "Device",
  "id": "withings-bpm-connect-555666777",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.withings.com/device-id",
      "value": "555666777",
      "assigner": {
        "display": "Withings Health Platform"
      }
    }
  ],
  "displayName": "BPM Connect",
  "type": [
    {
      "coding": [
        {
          "system": "http://snomed.info/sct",
          "code": "43770009",
          "display": "Sphygmomanometer"
        }
      ],
      "text": "Digital Blood Pressure Monitor"
    }
  ],
  "manufacturer": "Withings",
  "modelNumber": "BPM Connect",
  "serialNumber": "BPM-555666777",
  "version": [
    {
      "type": {
        "coding": [
          {
            "system": "http://terminology.hl7.org/CodeSystem/device-version-type",
            "code": "firmware-version"
          }
        ]
      },
      "value": "2.1.4"
    }
  ],
  "capability": [
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "85354-9",
            "display": "Blood pressure panel with all children optional"
          }
        ]
      },
      "description": "Automated blood pressure measurement with pulse detection"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "8867-4",
            "display": "Heart rate"
          }
        ]
      },
      "description": "Pulse rate detection during BP measurement"
    }
  ],
  "property": [
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "lastSyncTime",
            "display": "Last Sync Time"
          }
        ]
      },
      "valueDateTime": "2023-12-07T09:45:20Z"
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "cuff-size",
            "display": "Cuff Size"
          }
        ]
      },
      "valueString": "standard-adult"
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "measurement-range-systolic",
            "display": "Systolic Measurement Range"
          }
        ]
      },
      "valueRange": {
        "low": {
          "value": 70,
          "unit": "mmHg",
          "system": "http://unitsofmeasure.org",
          "code": "mm[Hg]"
        },
        "high": {
          "value": 230,
          "unit": "mmHg",
          "system": "http://unitsofmeasure.org",
          "code": "mm[Hg]"
        }
      }
    }
  ],
  "safety": [
    {
      "coding": [
        {
          "system": "https://open-health-exchange.org/CodeSystem/device-safety",
          "code": "validated-clinical",
          "display": "Clinically Validated"
        }
      ]
    }
  ],
  "note": [
    {
      "time": "2023-12-07T09:45:20Z",
      "text": "Wi-Fi enabled blood pressure monitor. Clinically validated accuracy. Suitable for home monitoring."
    }
  ]
}
```

### Blood Pressure Measurement

```json
{
  "resourceType": "Observation",
  "id": "bp-measurement-20231207094520",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.withings.com/measurement-id",
      "value": "bp-measurement-777888999"
    }
  ],
  "status": "final",
  "category": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/observation-category",
          "code": "vital-signs",
          "display": "Vital Signs"
        }
      ]
    }
  ],
  "code": {
    "coding": [
      {
        "system": "http://loinc.org",
        "code": "85354-9",
        "display": "Blood pressure panel with all children optional"
      }
    ],
    "text": "Blood pressure"
  },
  "subject": {
    "reference": "Patient/patient-john-doe"
  },
  "effectiveDateTime": "2023-12-07T09:45:20Z",
  "device": {
    "reference": "Device/withings-bpm-connect-555666777"
  },
  "component": [
    {
      "code": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "8480-6",
            "display": "Systolic blood pressure"
          }
        ],
        "text": "Systolic BP"
      },
      "valueQuantity": {
        "value": 118,
        "unit": "mmHg",
        "system": "http://unitsofmeasure.org",
        "code": "mm[Hg]"
      }
    },
    {
      "code": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "8462-4",
            "display": "Diastolic blood pressure"
          }
        ],
        "text": "Diastolic BP"
      },
      "valueQuantity": {
        "value": 76,
        "unit": "mmHg",
        "system": "http://unitsofmeasure.org",
        "code": "mm[Hg]"
      }
    },
    {
      "code": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "8867-4",
            "display": "Heart rate"
          }
        ],
        "text": "Pulse rate"
      },
      "valueQuantity": {
        "value": 72,
        "unit": "beats/min",
        "system": "http://unitsofmeasure.org",
        "code": "/min"
      }
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "measurement-quality",
            "display": "Measurement Quality"
          }
        ]
      },
      "valueString": "excellent"
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "arrhythmia-detected",
            "display": "Arrhythmia Detected"
          }
        ]
      },
      "valueBoolean": false
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "body-position",
            "display": "Body Position"
          }
        ]
      },
      "valueString": "sitting"
    }
  ],
  "interpretation": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
          "code": "N",
          "display": "Normal"
        }
      ],
      "text": "Normal blood pressure (118/76 mmHg)"
    }
  ],
  "bodySite": {
    "coding": [
      {
        "system": "http://snomed.info/sct",
        "code": "368209003",
        "display": "Right upper arm"
      }
    ]
  },
  "method": {
    "coding": [
      {
        "system": "http://snomed.info/sct",
        "code": "37931006",
        "display": "Oscillometry"
      }
    ]
  },
  "meta": {
    "tag": [
      {
        "system": "https://open-health-exchange.org/provider",
        "code": "withings",
        "display": "Withings"
      },
      {
        "system": "https://open-health-exchange.org/device-type",
        "code": "blood-pressure-monitor",
        "display": "Blood Pressure Monitor"
      }
    ],
    "source": "https://api.withings.com"
  }
}
```

---

## Pulse Oximeter (Fitbit Sense 2)

### Device Resource

```json
{
  "resourceType": "Device",
  "id": "fitbit-sense2-999888777",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.fitbit.com/device-id",
      "value": "999888777",
      "assigner": {
        "display": "Fitbit Platform"
      }
    }
  ],
  "displayName": "Jane's Fitbit Sense 2",
  "type": [
    {
      "coding": [
        {
          "system": "http://snomed.info/sct",
          "code": "258185003",
          "display": "Pulse oximeter"
        },
        {
          "system": "http://snomed.info/sct",
          "code": "706767009",
          "display": "Wearable device"
        }
      ],
      "text": "Smartwatch with Pulse Oximetry"
    }
  ],
  "manufacturer": "Fitbit",
  "modelNumber": "Sense 2",
  "serialNumber": "SENSE2-999888777",
  "version": [
    {
      "type": {
        "coding": [
          {
            "system": "http://terminology.hl7.org/CodeSystem/device-version-type",
            "code": "firmware-version"
          }
        ]
      },
      "value": "1.188.47"
    }
  ],
  "capability": [
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "2708-6",
            "display": "Oxygen saturation in Arterial blood"
          }
        ]
      },
      "description": "Continuous and on-demand SpO2 monitoring"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "8867-4",
            "display": "Heart rate"
          }
        ]
      },
      "description": "24/7 heart rate tracking with PurePulse 2.0"
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/measurement-type",
            "code": "stress-monitoring",
            "display": "Stress Monitoring"
          }
        ]
      },
      "description": "Continuous EDA stress monitoring"
    },
    {
      "type": {
        "coding": [
          {
            "system": "http://loinc.org",
            "code": "93832-4",
            "display": "Sleep study"
          }
        ]
      },
      "description": "Sleep score and sleep stages tracking"
    }
  ],
  "property": [
    {
      "type": {
        "coding": [
          {
            "system": "http://terminology.hl7.org/CodeSystem/device-property-type",
            "code": "battery-level",
            "display": "Battery Level"
          }
        ]
      },
      "valueQuantity": {
        "value": 92,
        "unit": "%",
        "system": "http://unitsofmeasure.org",
        "code": "%"
      }
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "lastSyncTime",
            "display": "Last Sync Time"
          }
        ]
      },
      "valueDateTime": "2023-12-07T10:22:45Z"
    },
    {
      "type": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/device-property-type",
            "code": "gps-enabled",
            "display": "GPS Enabled"
          }
        ]
      },
      "valueBoolean": true
    }
  ],
  "safety": [
    {
      "coding": [
        {
          "system": "urn:oid:2.16.840.1.113883.3.26.1.1",
          "code": "mr-unsafe",
          "display": "MR Unsafe"
        }
      ]
    }
  ],
  "note": [
    {
      "time": "2023-12-07T10:22:45Z",
      "text": "Advanced health and fitness smartwatch. SpO2 monitoring not intended for medical diagnosis. Water resistant up to 50 meters."
    }
  ]
}
```

### SpO2 Observation

```json
{
  "resourceType": "Observation",
  "id": "spo2-measurement-20231207102245",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.fitbit.com/measurement-id",
      "value": "spo2-measurement-111222333"
    }
  ],
  "status": "final",
  "category": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/observation-category",
          "code": "vital-signs",
          "display": "Vital Signs"
        }
      ]
    }
  ],
  "code": {
    "coding": [
      {
        "system": "http://loinc.org",
        "code": "2708-6",
        "display": "Oxygen saturation in Arterial blood"
      }
    ],
    "text": "Oxygen saturation (SpO2)"
  },
  "subject": {
    "reference": "Patient/patient-jane-smith"
  },
  "effectiveDateTime": "2023-12-07T10:22:45Z",
  "valueQuantity": {
    "value": 97,
    "unit": "%",
    "system": "http://unitsofmeasure.org",
    "code": "%"
  },
  "device": {
    "reference": "Device/fitbit-sense2-999888777"
  },
  "component": [
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "measurement-quality",
            "display": "Measurement Quality"
          }
        ]
      },
      "valueString": "high"
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "measurement-type",
            "display": "Measurement Type"
          }
        ]
      },
      "valueString": "on-demand"
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "ambient-temperature",
            "display": "Ambient Temperature"
          }
        ]
      },
      "valueQuantity": {
        "value": 22,
        "unit": "Cel",
        "system": "http://unitsofmeasure.org",
        "code": "Cel"
      }
    }
  ],
  "interpretation": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
          "code": "N",
          "display": "Normal"
        }
      ],
      "text": "Normal oxygen saturation (97%)"
    }
  ],
  "bodySite": {
    "coding": [
      {
        "system": "http://snomed.info/sct",
        "code": "74262004",
        "display": "Wrist region structure"
      }
    ]
  },
  "method": {
    "coding": [
      {
        "system": "http://snomed.info/sct",
        "code": "252465000",
        "display": "Pulse oximetry"
      }
    ]
  },
  "referenceRange": [
    {
      "low": {
        "value": 95,
        "unit": "%",
        "system": "http://unitsofmeasure.org",
        "code": "%"
      },
      "high": {
        "value": 100,
        "unit": "%",
        "system": "http://unitsofmeasure.org",
        "code": "%"
      },
      "type": {
        "coding": [
          {
            "system": "http://terminology.hl7.org/CodeSystem/referencerange-meaning",
            "code": "normal",
            "display": "Normal Range"
          }
        ]
      },
      "text": "Normal range for healthy adults at sea level"
    }
  ],
  "meta": {
    "tag": [
      {
        "system": "https://open-health-exchange.org/provider",
        "code": "fitbit",
        "display": "Fitbit"
      },
      {
        "system": "https://open-health-exchange.org/device-type",
        "code": "pulse-oximeter",
        "display": "Pulse Oximeter"
      }
    ],
    "source": "https://api.fitbit.com",
    "versionId": "1",
    "lastUpdated": "2023-12-07T10:23:00Z"
  }
}
```

### SpO2 Trend Observation (Sleep Period)

```json
{
  "resourceType": "Observation",
  "id": "spo2-sleep-trend-20231207",
  "identifier": [
    {
      "use": "official",
      "system": "https://api.fitbit.com/sleep-spo2-id",
      "value": "sleep-spo2-444555666"
    }
  ],
  "status": "final",
  "category": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/observation-category",
          "code": "vital-signs",
          "display": "Vital Signs"
        }
      ]
    }
  ],
  "code": {
    "coding": [
      {
        "system": "http://loinc.org",
        "code": "2708-6",
        "display": "Oxygen saturation in Arterial blood"
      }
    ],
    "text": "Sleep SpO2 variation"
  },
  "subject": {
    "reference": "Patient/patient-jane-smith"
  },
  "effectivePeriod": {
    "start": "2023-12-06T23:15:00Z",
    "end": "2023-12-07T07:30:00Z"
  },
  "device": {
    "reference": "Device/fitbit-sense2-999888777"
  },
  "component": [
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "spo2-average",
            "display": "Average SpO2"
          }
        ]
      },
      "valueQuantity": {
        "value": 96.2,
        "unit": "%",
        "system": "http://unitsofmeasure.org",
        "code": "%"
      }
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "spo2-minimum",
            "display": "Minimum SpO2"
          }
        ]
      },
      "valueQuantity": {
        "value": 93,
        "unit": "%",
        "system": "http://unitsofmeasure.org",
        "code": "%"
      }
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "spo2-maximum",
            "display": "Maximum SpO2"
          }
        ]
      },
      "valueQuantity": {
        "value": 98,
        "unit": "%",
        "system": "http://unitsofmeasure.org",
        "code": "%"
      }
    },
    {
      "code": {
        "coding": [
          {
            "system": "https://open-health-exchange.org/CodeSystem/observation-component",
            "code": "measurement-context",
            "display": "Measurement Context"
          }
        ]
      },
      "valueString": "sleep"
    }
  ],
  "interpretation": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
          "code": "N",
          "display": "Normal"
        }
      ],
      "text": "Normal overnight SpO2 variation (93-98%)"
    }
  ],
  "note": [
    {
      "text": "Continuous overnight SpO2 monitoring during sleep. Data collected every 15 seconds. No significant desaturations detected."
    }
  ],
  "meta": {
    "tag": [
      {
        "system": "https://open-health-exchange.org/provider",
        "code": "fitbit",
        "display": "Fitbit"
      },
      {
        "system": "https://open-health-exchange.org/measurement-context",
        "code": "sleep-monitoring",
        "display": "Sleep Monitoring"
      }
    ],
    "source": "https://api.fitbit.com"
  }
}
```

---

## Device Comparison Summary

| Device Type | Provider | Key Measurements | FHIR Resources | SNOMED CT Code |
|-------------|----------|------------------|----------------|----------------|
| **SmartWatch** | Withings ScanWatch 2 | Heart Rate, ECG, Steps, Sleep | Device, Observation, DiagnosticReport | 706767009 |
| **Smart Scale** | Withings Body+ | Weight, BMI, Body Fat, Muscle Mass | Device, Observation Bundle | 19892000 |
| **BP Monitor** | Withings BPM Connect | Systolic/Diastolic BP, Pulse | Device, Observation | 43770009 |
| **Pulse Oximeter** | Fitbit Sense 2 | SpO2, Heart Rate, Sleep SpO2 | Device, Observation | 258185003 |

## LOINC Code Reference

| Measurement | LOINC Code | Display Name | Unit |
|-------------|------------|--------------|------|
| Heart Rate | 8867-4 | Heart rate | /min |
| ECG | 131328-5 | Electrocardiogram study | - |
| Weight | 29463-7 | Body weight | kg |
| BMI | 39156-5 | Body mass index (BMI) [Ratio] | kg/m2 |
| Body Fat | 41982-0 | Percentage of body fat | % |
| Systolic BP | 8480-6 | Systolic blood pressure | mmHg |
| Diastolic BP | 8462-4 | Diastolic blood pressure | mmHg |
| SpO2 | 2708-6 | Oxygen saturation in Arterial blood | % |
| Steps | 55423-8 | Number of steps | 1 |
| Sleep | 93832-4 | Sleep study | - |

## Integration Notes

### Data Quality Indicators
- **Measurement Quality**: Indicates signal strength and accuracy
- **Measurement Context**: Resting, active, sleep, etc.
- **Body Position**: Sitting, standing, lying for BP measurements
- **Ambient Conditions**: Temperature, altitude for SpO2

### Device Properties
- **Battery Level**: Current charge percentage
- **Last Sync Time**: When device last synchronized
- **Firmware Version**: Device software version
- **Connectivity**: Wi-Fi, Bluetooth status

### Clinical Considerations
- All measurements include reference ranges where applicable
- Interpretations follow standard clinical guidelines
- Device limitations and warnings included in notes
- Proper SNOMED CT and LOINC coding for interoperability
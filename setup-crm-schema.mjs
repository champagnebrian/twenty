#!/usr/bin/env node
/**
 * setup-crm-schema.mjs
 *
 * Builds the complete nightclub/hospitality CRM schema in Twenty via the Metadata API.
 * Run with: node setup-crm-schema.mjs
 * Requires Node.js 18+ (native fetch).
 */

// ─── CONFIG ─────────────────────────────────────────────────────────────────

const BASE_URL = 'https://ant-silver-rhino.twenty.com';
const API_KEY =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyOTYyZTM0Mi1kNDVjLTRiN2YtODdkOS1mNmE0NDhkMzE3NWYiLCJ0eXBlIjoiQVBJX0tFWSIsIndvcmtzcGFjZUlkIjoiMjk2MmUzNDItZDQ1Yy00YjdmLTg3ZDktZjZhNDQ4ZDMxNzVmIiwiaWF0IjoxNzc0Njg5MTI1LCJleHAiOjQ5MjgyOTI3MjQsImp0aSI6IjNjNmFmOTJkLTM0ZWQtNDQwMS04Y2ExLTZhOTBiYWUyM2U5NSJ9.KQhUTVy2J7wie9EMk_XiXMB4VkgXxTgpYw-ghSDBE0E';

// ─── COLOR ROTATION ──────────────────────────────────────────────────────────

const TAG_COLORS = [
  'green', 'turquoise', 'sky', 'blue', 'purple',
  'pink', 'red', 'orange', 'yellow', 'gray',
];
const c = (i) => TAG_COLORS[i % TAG_COLORS.length];

// Build SELECT/MULTI_SELECT options from a labels array.
// Each label is mapped to a SCREAMING_SNAKE_CASE value safe for GraphQL enums.
function opts(labels) {
  return labels.map((label, i) => ({
    value: toEnumValue(label),
    label,
    color: c(i),
    position: i,
  }));
}

function toEnumValue(label) {
  return label
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/^([0-9])/, 'N$1'); // enum values cannot start with digit
}

// ─── API HELPERS ─────────────────────────────────────────────────────────────

async function metadataRequest(query, variables = {}) {
  const res = await fetch(`${BASE_URL}/metadata`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query, variables }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }

  const json = await res.json();

  if (json.errors?.length) {
    throw new Error(JSON.stringify(json.errors, null, 2));
  }

  return json.data;
}

async function createObject({ nameSingular, namePlural, labelSingular, labelPlural, icon = 'IconStar', description }) {
  process.stdout.write(`  Creating object: ${labelSingular}... `);
  const data = await metadataRequest(
    `mutation CreateOneObjectMetadataItem($input: CreateOneObjectInput!) {
       createOneObject(input: $input) { id nameSingular }
     }`,
    { input: { object: { nameSingular, namePlural, labelSingular, labelPlural, icon, description } } },
  );
  console.log(`✓ (${data.createOneObject.id})`);
  return data.createOneObject;
}

async function createField(objectMetadataId, { name, label, type, options, settings, description, isNullable = true, defaultValue }) {
  process.stdout.write(`    Field: ${label} (${type})... `);
  const fieldInput = {
    objectMetadataId,
    name,
    label,
    type,
    isNullable,
    ...(description !== undefined && { description }),
    ...(options !== undefined && { options }),
    ...(settings !== undefined && { settings }),
    ...(defaultValue !== undefined && { defaultValue }),
  };

  const data = await metadataRequest(
    `mutation CreateOneFieldMetadataItem($input: CreateOneFieldMetadataInput!) {
       createOneField(input: $input) { id name label type }
     }`,
    { input: { field: fieldInput } },
  );
  console.log(`✓`);
  return data.createOneField;
}

async function createFields(objectMetadataId, fieldDefs) {
  const result = {};
  for (const def of fieldDefs) {
    try {
      const field = await createField(objectMetadataId, def);
      result[def.name] = field;
    } catch (err) {
      console.error(`\n    ✗ FAILED field "${def.label}": ${err.message}\n`);
    }
  }
  return result;
}

async function createRelation({ sourceObjectId, targetObjectId, fieldName, fieldLabel, targetFieldLabel, targetFieldIcon = 'IconList' }) {
  process.stdout.write(`    Relation: ${fieldLabel} → ${targetFieldLabel}... `);
  const data = await metadataRequest(
    `mutation CreateOneFieldMetadataItem($input: CreateOneFieldMetadataInput!) {
       createOneField(input: $input) { id name label type }
     }`,
    {
      input: {
        field: {
          objectMetadataId: sourceObjectId,
          name: fieldName,
          label: fieldLabel,
          type: 'RELATION',
          isNullable: true,
          relationCreationPayload: {
            targetObjectMetadataId: targetObjectId,
            targetFieldLabel,
            targetFieldIcon,
            type: 'MANY_TO_ONE',
          },
        },
      },
    },
  );
  console.log(`✓`);
  return data.createOneField;
}

async function createView({ objectMetadataId, name, type = 'KANBAN', icon = 'IconLayoutKanban', mainGroupByFieldMetadataId, position = 1 }) {
  process.stdout.write(`  View: "${name}"... `);
  const data = await metadataRequest(
    `mutation CreateView($input: CreateViewInput!) {
       createView(input: $input) { id name type }
     }`,
    {
      input: {
        objectMetadataId,
        name,
        type,
        icon,
        position,
        ...(mainGroupByFieldMetadataId && { mainGroupByFieldMetadataId }),
      },
    },
  );
  console.log(`✓ (${data.createView.id})`);
  return data.createView;
}

async function createManyViewGroups(viewId, stages) {
  process.stdout.write(`  View groups: [${stages.map((s) => s.fieldValue).join(', ')}]... `);
  const inputs = stages.map((s, i) => ({
    viewId,
    fieldValue: s.fieldValue,
    position: i,
    isVisible: true,
  }));
  const data = await metadataRequest(
    `mutation CreateManyViewGroups($inputs: [CreateViewGroupInput!]!) {
       createManyViewGroups(inputs: $inputs) { id fieldValue }
     }`,
    { inputs },
  );
  console.log(`✓`);
  return data.createManyViewGroups;
}

// ─── FIELD DEFINITIONS ───────────────────────────────────────────────────────

// VIP Guests fields (FULL_NAME "name" field is auto-created with the object)
const VIP_GUEST_FIELDS = [
  { name: 'phones',                label: 'Phones',                 type: 'PHONES'      },
  { name: 'email',                 label: 'Email',                  type: 'EMAILS'      },
  { name: 'instagramHandle',       label: 'Instagram Handle',       type: 'TEXT'        },
  { name: 'address',               label: 'Address',                type: 'ADDRESS'     },
  { name: 'profilePhoto',          label: 'Profile Photo',          type: 'FILES'       },
  { name: 'nationality',           label: 'Nationality',            type: 'TEXT'        },
  { name: 'languagePreference',    label: 'Language Preference',    type: 'TEXT'        },
  {
    name: 'hotelResidency', label: 'Hotel / Residency', type: 'SELECT',
    options: opts(['Cosmopolitan', 'Wynn', 'Aria', 'Bellagio', 'MGM', 'Venetian', 'Encore', 'Other']),
  },
  {
    name: 'tier', label: 'Tier', type: 'SELECT',
    options: opts(['Bronze', 'Silver', 'Gold', 'VIP', 'VVIP', 'Whale']),
  },
  {
    name: 'tags', label: 'Tags', type: 'MULTI_SELECT',
    options: opts(['Celebrity', 'Athlete', 'VVIP', 'Millionaire', 'Billionaire', 'Industry',
                   'Local', 'Bachelor Party', 'Bachelorette', 'Wedding', 'Boys Trip', 'Birthday',
                   'Conference', 'Hotel Guest', 'FDL']),
  },
  {
    name: 'guestOrigin', label: 'Guest Origin', type: 'SELECT',
    options: opts(['Host Referral', 'Lead', 'Concierge', 'FDL', 'Referral', 'Walk-Up']),
  },
  { name: 'lifetimeTotalSpend',    label: 'Lifetime Total Spend',   type: 'CURRENCY'    },
  { name: 'averageSpendPerVisit',  label: 'Average Spend Per Visit',type: 'CURRENCY'    },
  { name: 'averagePctOverMinimum', label: 'Average % Over Minimum', type: 'NUMBER'      },
  { name: 'visitCount',            label: 'Visit Count',            type: 'NUMBER'      },
  { name: 'prestigeBottleSpend',   label: 'Prestige Bottle Spend',  type: 'CURRENCY'    },
  { name: 'standardBottleSpend',   label: 'Standard Bottle Spend',  type: 'CURRENCY'    },
  { name: 'addOnSpend',            label: 'Add-On Spend',           type: 'CURRENCY'    },
  {
    name: 'milestoneTier', label: 'Milestone Tier', type: 'SELECT',
    options: opts(['First Visit', '$10K Club', '$50K Club', '$100K Club', '$250K+']),
  },
  { name: 'preferredSection',      label: 'Preferred Section',      type: 'TEXT'        },
  { name: 'preferredTableNumber',  label: 'Preferred Table Number', type: 'TEXT'        },
  { name: 'bottlePreferences',     label: 'Bottle Preferences',     type: 'TEXT'        },
  { name: 'specialNotes',          label: 'Special Notes',          type: 'TEXT'        },
  { name: 'noShowCount',           label: 'No-Show Count',          type: 'NUMBER'      },
  { name: 'cancellationCount',     label: 'Cancellation Count',     type: 'NUMBER'      },
  {
    name: 'reliabilityFlag', label: 'Reliability Flag', type: 'SELECT',
    options: opts(['Reliable', 'Watch', 'Unreliable']),
  },
  { name: 'dateOfBirth',           label: 'Date of Birth',          type: 'DATE'        },
  { name: 'birthdayMonth',         label: 'Birthday Month',         type: 'NUMBER'      },
  { name: 'firstVisitDate',        label: 'First Visit Date',       type: 'DATE'        },
  { name: 'lastVisitDate',         label: 'Last Visit Date',        type: 'DATE'        },
  { name: 'lastContactDate',       label: 'Last Contact Date',      type: 'DATE'        },
  { name: 'blacklisted',           label: 'Blacklisted',            type: 'BOOLEAN', defaultValue: false },
  {
    name: 'blacklistReason', label: 'Blacklist Reason', type: 'SELECT',
    options: opts(['Chargeback', 'Violence', 'Theft', 'Behavior', 'Management Ban']),
  },
  { name: 'blacklistDate',         label: 'Blacklist Date',         type: 'DATE'        },
  { name: 'flaggedForReview',      label: 'Flagged For Review',     type: 'BOOLEAN', defaultValue: false },
  { name: 'alertNote',             label: 'Alert Note',             type: 'TEXT'        },
  {
    name: 'guestSentiment', label: 'Guest Sentiment', type: 'SELECT',
    options: opts(['5-Star', '4-Star', '3-Star', 'Had Issues']),
  },
  { name: 'followUpDate',          label: 'Follow-Up Date',         type: 'DATE'        },
  { name: 'followUpNote',          label: 'Follow-Up Note',         type: 'TEXT'        },
  {
    name: 'status', label: 'Status', type: 'SELECT',
    options: opts(['Active', 'Dormant', 'Blacklisted']),
  },
  // Used as the groupBy field for the VIP Relationship Pipeline
  {
    name: 'relationshipStage', label: 'Relationship Stage', type: 'SELECT',
    options: opts(['New Guest', 'One-Time', 'Returning', 'VIP Regular', 'VVIP', 'Whale']),
  },
];

// Hosts and Promoters
const HOST_PROMOTER_FIELDS = [
  { name: 'phones',                   label: 'Phones',                      type: 'PHONES'   },
  { name: 'email',                    label: 'Email',                       type: 'EMAILS'   },
  { name: 'instagramHandle',          label: 'Instagram Handle',            type: 'TEXT'     },
  { name: 'mailingAddress',           label: 'Mailing Address',             type: 'TEXT'     },
  { name: 'profilePhoto',             label: 'Profile Photo',               type: 'FILES'    },
  {
    name: 'hostType', label: 'Type', type: 'SELECT',
    options: opts(['In-House Host', 'Independent Promoter', 'External Agency', 'Concierge', 'FDL']),
  },
  { name: 'totalClientsReferred',     label: 'Total Clients Referred',      type: 'NUMBER'   },
  { name: 'totalRevenueAttributed',   label: 'Total Revenue Attributed',    type: 'CURRENCY' },
  { name: 'averageClientSpend',       label: 'Average Client Spend',        type: 'CURRENCY' },
  { name: 'averageClientPctOverMin',  label: 'Average Client % Over Minimum', type: 'NUMBER' },
  { name: 'commissionRate',           label: 'Commission Rate',             type: 'TEXT'     },
  { name: 'compValueOwed',            label: 'Comp Value Owed',             type: 'CURRENCY' },
  { name: 'followUpDate',             label: 'Follow-Up Date',              type: 'DATE'     },
  { name: 'followUpNote',             label: 'Follow-Up Note',              type: 'TEXT'     },
  { name: 'lastContactDate',          label: 'Last Contact Date',           type: 'DATE'     },
  {
    name: 'status', label: 'Status', type: 'SELECT',
    options: opts(['Active', 'Inactive']),
  },
];

// Concierge and FDL Contacts
const CONCIERGE_FIELDS = [
  { name: 'phones',              label: 'Primary Phone',          type: 'PHONES'   },
  { name: 'email',               label: 'Email',                  type: 'EMAILS'   },
  { name: 'instagramHandle',     label: 'Instagram Handle',       type: 'TEXT'     },
  {
    name: 'hotelCompany', label: 'Hotel / Company', type: 'SELECT',
    options: opts(['Cosmopolitan', 'Wynn', 'Aria', 'Bellagio', 'MGM', 'Venetian', 'Encore', 'Independent']),
  },
  { name: 'roleTitle',           label: 'Role / Title',           type: 'TEXT'     },
  { name: 'totalGuestsSent',     label: 'Total Guests Sent',      type: 'NUMBER'   },
  { name: 'totalRevenueGenerated', label: 'Total Revenue Generated', type: 'CURRENCY' },
  { name: 'averageGuestSpend',   label: 'Average Guest Spend',    type: 'CURRENCY' },
  {
    name: 'relationshipQuality', label: 'Relationship Quality', type: 'SELECT',
    options: opts(['Priority', 'Warm', 'Cold', 'Inactive']),
  },
  { name: 'lastOutreachDate',    label: 'Last Outreach Date',     type: 'DATE'     },
  { name: 'followUpDate',        label: 'Follow-Up Date',         type: 'DATE'     },
  { name: 'followUpNote',        label: 'Follow-Up Note',         type: 'TEXT'     },
  { name: 'notes',               label: 'Notes',                  type: 'TEXT'     },
  // Used as the groupBy field for the Concierge Pipeline
  {
    name: 'conciergeStage', label: 'Concierge Stage', type: 'SELECT',
    options: opts(['Cold', 'Warm', 'Priority', 'Strategic Partner']),
  },
];

// Table Bookings (skipNameField: true — bookingName is a plain TEXT field)
const TABLE_BOOKING_FIELDS = [
  { name: 'bookingName',         label: 'Booking Name',           type: 'TEXT'     },
  { name: 'bookingDate',         label: 'Date',                   type: 'DATE'     },
  { name: 'tableNumber',         label: 'Table Number',           type: 'TEXT'     },
  { name: 'section',             label: 'Section',                type: 'TEXT'     },
  { name: 'partySize',           label: 'Party Size',             type: 'NUMBER'   },
  { name: 'minimumSpend',        label: 'Minimum Spend',          type: 'CURRENCY' },
  { name: 'actualSpend',         label: 'Actual Spend',           type: 'CURRENCY' },
  { name: 'dollarOverMinimum',   label: 'Dollar Over Minimum',    type: 'CURRENCY' },
  { name: 'percentOverMinimum',  label: 'Percent Over Minimum',   type: 'NUMBER'   },
  { name: 'prestigeBottleSpend', label: 'Prestige Bottle Spend',  type: 'CURRENCY' },
  { name: 'standardBottleSpend', label: 'Standard Bottle Spend',  type: 'CURRENCY' },
  { name: 'addOnSpend',          label: 'Add-On Spend',           type: 'CURRENCY' },
  { name: 'compItems',           label: 'Comp Items',             type: 'TEXT'     },
  { name: 'compValue',           label: 'Comp Value',             type: 'CURRENCY' },
  { name: 'netRevenue',          label: 'Net Revenue',            type: 'CURRENCY' },
  {
    name: 'paymentMethod', label: 'Payment Method', type: 'SELECT',
    options: opts(['Card', 'Cash', 'Comped', 'Split']),
  },
  // Used as the groupBy field for the Booking Pipeline
  {
    name: 'bookingStatus', label: 'Booking Status', type: 'SELECT',
    options: opts(['Inquiry', 'Deposit Received', 'Confirmed', 'Night Of', 'Completed', 'No-Show', 'Cancelled']),
  },
  {
    name: 'guestSentiment', label: 'Guest Sentiment', type: 'SELECT',
    options: opts(['5-Star', '4-Star', '3-Star', 'Had Issues']),
  },
  { name: 'issueNotes',          label: 'Issue Notes',            type: 'TEXT'     },
  { name: 'specialRequests',     label: 'Special Requests',       type: 'TEXT'     },
  { name: 'postVisitFollowUpDate', label: 'Post-Visit Follow-Up Date', type: 'DATE' },
  { name: 'followUpNote',        label: 'Follow-Up Note',         type: 'TEXT'     },
];

// Bottle Orders
const BOTTLE_ORDER_FIELDS = [
  { name: 'bottleName',     label: 'Bottle Name',          type: 'TEXT'     },
  {
    name: 'category', label: 'Category', type: 'SELECT',
    options: opts(['Champagne', 'Vodka', 'Tequila', 'Whiskey', 'Cognac', 'Add-On', 'Experience']),
  },
  { name: 'brand',          label: 'Brand',                type: 'TEXT'     },
  { name: 'quantity',       label: 'Quantity',             type: 'NUMBER'   },
  { name: 'pricePerBottle', label: 'Price Per Bottle',     type: 'CURRENCY' },
  { name: 'lineTotal',      label: 'Line Total',           type: 'CURRENCY' },
  { name: 'comped',         label: 'Comped',               type: 'BOOLEAN', defaultValue: false },
  { name: 'compValue',      label: 'Comp Value',           type: 'CURRENCY' },
];

// Events and Nights
const EVENT_NIGHT_FIELDS = [
  { name: 'eventName',            label: 'Event Name',             type: 'TEXT'     },
  { name: 'eventDate',            label: 'Date',                   type: 'DATE'     },
  { name: 'dayOfWeek',            label: 'Day of Week',            type: 'TEXT'     },
  {
    name: 'eventType', label: 'Type', type: 'SELECT',
    options: opts(['DJ Night', 'Special Event', 'Holiday', 'Buyout', 'Residency']),
  },
  { name: 'expectedCapacity',     label: 'Expected Capacity',      type: 'NUMBER'   },
  { name: 'totalTablesAvailable', label: 'Total Tables Available', type: 'NUMBER'   },
  { name: 'notes',                label: 'Notes',                  type: 'TEXT'     },
  { name: 'totalBookings',        label: 'Total Bookings',         type: 'NUMBER'   },
  { name: 'totalRevenue',         label: 'Total Revenue',          type: 'CURRENCY' },
  { name: 'averageTableSpend',    label: 'Average Table Spend',    type: 'CURRENCY' },
  { name: 'averagePctOverMin',    label: 'Average % Over Minimum', type: 'NUMBER'   },
  { name: 'noShowCount',          label: 'No-Show Count',          type: 'NUMBER'   },
];

// Communication Log
const COMM_LOG_FIELDS = [
  { name: 'logDateTime',     label: 'Date and Time',     type: 'DATE_TIME' },
  {
    name: 'channel', label: 'Channel', type: 'SELECT',
    options: opts(['SMS', 'Call', 'Instagram DM', 'In-Person']),
  },
  {
    name: 'direction', label: 'Direction', type: 'SELECT',
    options: opts(['Outbound', 'Inbound']),
  },
  { name: 'summary',         label: 'Summary',           type: 'TEXT'      },
  { name: 'followUpRequired', label: 'Follow-Up Required', type: 'BOOLEAN', defaultValue: false },
];

// ─── MAIN ─────────────────────────────────────────────────────────────────────

async function main() {
  console.log('═══════════════════════════════════════════════════════════');
  console.log('  Twenty CRM — Nightclub Schema Setup');
  console.log('═══════════════════════════════════════════════════════════\n');

  // ── Phase 1: Create Objects ──────────────────────────────────────────────

  console.log('PHASE 1: Creating objects...\n');

  const objects = {};

  try {
    objects.vipGuest = await createObject({
      nameSingular: 'vipGuest',
      namePlural: 'vipGuests',
      labelSingular: 'VIP Guest',
      labelPlural: 'VIP Guests',
      icon: 'IconStar',
      description: 'High-value nightclub guests',
    });
  } catch (e) { console.error(`✗ vipGuest: ${e.message}`); }

  try {
    objects.hostPromoter = await createObject({
      nameSingular: 'hostPromoter',
      namePlural: 'hostPromoters',
      labelSingular: 'Host / Promoter',
      labelPlural: 'Hosts and Promoters',
      icon: 'IconUserStar',
      description: 'In-house hosts, independent promoters, and external agencies',
    });
  } catch (e) { console.error(`✗ hostPromoter: ${e.message}`); }

  try {
    objects.conciergeContact = await createObject({
      nameSingular: 'conciergeContact',
      namePlural: 'conciergeContacts',
      labelSingular: 'Concierge Contact',
      labelPlural: 'Concierge and FDL Contacts',
      icon: 'IconBuildingSkyscraper',
      description: 'Hotel concierge and FDL contacts',
    });
  } catch (e) { console.error(`✗ conciergeContact: ${e.message}`); }

  try {
    objects.tableBooking = await createObject({
      nameSingular: 'tableBooking',
      namePlural: 'tableBookings',
      labelSingular: 'Table Booking',
      labelPlural: 'Table Bookings',
      icon: 'IconTable',
      description: 'VIP table reservations and spend tracking',
    });
  } catch (e) { console.error(`✗ tableBooking: ${e.message}`); }

  try {
    objects.bottleOrder = await createObject({
      nameSingular: 'bottleOrder',
      namePlural: 'bottleOrders',
      labelSingular: 'Bottle Order',
      labelPlural: 'Bottle Orders',
      icon: 'IconBottle',
      description: 'Individual bottle orders within a table booking',
    });
  } catch (e) { console.error(`✗ bottleOrder: ${e.message}`); }

  try {
    objects.eventNight = await createObject({
      nameSingular: 'eventNight',
      namePlural: 'eventNights',
      labelSingular: 'Event / Night',
      labelPlural: 'Events and Nights',
      icon: 'IconCalendarEvent',
      description: 'Nightclub events, DJ nights, and special occasions',
    });
  } catch (e) { console.error(`✗ eventNight: ${e.message}`); }

  try {
    objects.communicationLog = await createObject({
      nameSingular: 'communicationLog',
      namePlural: 'communicationLogs',
      labelSingular: 'Communication Log',
      labelPlural: 'Communication Logs',
      icon: 'IconMessage',
      description: 'Outbound and inbound guest communications',
    });
  } catch (e) { console.error(`✗ communicationLog: ${e.message}`); }

  console.log('\nObjects created:\n', Object.fromEntries(
    Object.entries(objects).map(([k, v]) => [k, v?.id ?? 'FAILED']),
  ), '\n');

  // ── Phase 2: Create Fields ───────────────────────────────────────────────

  console.log('PHASE 2: Creating fields...\n');

  const fields = {};

  if (objects.vipGuest) {
    console.log('  → VIP Guests');
    fields.vipGuest = await createFields(objects.vipGuest.id, VIP_GUEST_FIELDS);
  }

  if (objects.hostPromoter) {
    console.log('\n  → Hosts and Promoters');
    fields.hostPromoter = await createFields(objects.hostPromoter.id, HOST_PROMOTER_FIELDS);
  }

  if (objects.conciergeContact) {
    console.log('\n  → Concierge and FDL Contacts');
    fields.conciergeContact = await createFields(objects.conciergeContact.id, CONCIERGE_FIELDS);
  }

  if (objects.tableBooking) {
    console.log('\n  → Table Bookings');
    fields.tableBooking = await createFields(objects.tableBooking.id, TABLE_BOOKING_FIELDS);
  }

  if (objects.bottleOrder) {
    console.log('\n  → Bottle Orders');
    fields.bottleOrder = await createFields(objects.bottleOrder.id, BOTTLE_ORDER_FIELDS);
  }

  if (objects.eventNight) {
    console.log('\n  → Events and Nights');
    fields.eventNight = await createFields(objects.eventNight.id, EVENT_NIGHT_FIELDS);
  }

  if (objects.communicationLog) {
    console.log('\n  → Communication Log');
    fields.communicationLog = await createFields(objects.communicationLog.id, COMM_LOG_FIELDS);
  }

  // ── Phase 3: Create Relationships ────────────────────────────────────────

  console.log('\nPHASE 3: Creating relationships...\n');

  const relations = [
    // VIP Guest → Referred By → Host/Promoter (many-to-one)
    objects.vipGuest && objects.hostPromoter && {
      sourceObjectId: objects.vipGuest.id,
      targetObjectId: objects.hostPromoter.id,
      fieldName: 'referredBy',
      fieldLabel: 'Referred By',
      targetFieldLabel: 'Referred VIP Guests',
      targetFieldIcon: 'IconStar',
    },
    // VIP Guest → Host Owner → Host/Promoter (many-to-one)
    objects.vipGuest && objects.hostPromoter && {
      sourceObjectId: objects.vipGuest.id,
      targetObjectId: objects.hostPromoter.id,
      fieldName: 'hostOwner',
      fieldLabel: 'Host Owner',
      targetFieldLabel: 'Owned VIP Guests',
      targetFieldIcon: 'IconUserStar',
    },
    // VIP Guest → Referral Chain → VIP Guest (self many-to-one)
    objects.vipGuest && {
      sourceObjectId: objects.vipGuest.id,
      targetObjectId: objects.vipGuest.id,
      fieldName: 'referralSource',
      fieldLabel: 'Referral Source',
      targetFieldLabel: 'Referred Guests',
      targetFieldIcon: 'IconArrowRight',
    },
    // VIP Guest → Known Associate → VIP Guest (self many-to-one, approximation of many-to-many)
    objects.vipGuest && {
      sourceObjectId: objects.vipGuest.id,
      targetObjectId: objects.vipGuest.id,
      fieldName: 'knownAssociate',
      fieldLabel: 'Known Associate',
      targetFieldLabel: 'Associated With',
      targetFieldIcon: 'IconUsers',
    },
    // Table Booking → VIP Guest (many-to-one)
    objects.tableBooking && objects.vipGuest && {
      sourceObjectId: objects.tableBooking.id,
      targetObjectId: objects.vipGuest.id,
      fieldName: 'vipGuest',
      fieldLabel: 'VIP Guest',
      targetFieldLabel: 'Table Bookings',
      targetFieldIcon: 'IconTable',
    },
    // Table Booking → Host/Promoter (many-to-one)
    objects.tableBooking && objects.hostPromoter && {
      sourceObjectId: objects.tableBooking.id,
      targetObjectId: objects.hostPromoter.id,
      fieldName: 'hostPromoter',
      fieldLabel: 'Host / Promoter',
      targetFieldLabel: 'Table Bookings',
      targetFieldIcon: 'IconTable',
    },
    // Table Booking → Concierge Contact (many-to-one)
    objects.tableBooking && objects.conciergeContact && {
      sourceObjectId: objects.tableBooking.id,
      targetObjectId: objects.conciergeContact.id,
      fieldName: 'conciergeContact',
      fieldLabel: 'Concierge Contact',
      targetFieldLabel: 'Table Bookings',
      targetFieldIcon: 'IconTable',
    },
    // Table Booking → Event/Night (many-to-one)
    objects.tableBooking && objects.eventNight && {
      sourceObjectId: objects.tableBooking.id,
      targetObjectId: objects.eventNight.id,
      fieldName: 'eventNight',
      fieldLabel: 'Event / Night',
      targetFieldLabel: 'Table Bookings',
      targetFieldIcon: 'IconTable',
    },
    // Bottle Order → Table Booking (many-to-one)
    objects.bottleOrder && objects.tableBooking && {
      sourceObjectId: objects.bottleOrder.id,
      targetObjectId: objects.tableBooking.id,
      fieldName: 'tableBooking',
      fieldLabel: 'Table Booking',
      targetFieldLabel: 'Bottle Orders',
      targetFieldIcon: 'IconBottle',
    },
    // Communication Log → VIP Guest (many-to-one)
    objects.communicationLog && objects.vipGuest && {
      sourceObjectId: objects.communicationLog.id,
      targetObjectId: objects.vipGuest.id,
      fieldName: 'vipGuest',
      fieldLabel: 'VIP Guest',
      targetFieldLabel: 'Communications',
      targetFieldIcon: 'IconMessage',
    },
    // Communication Log → Host/Promoter (many-to-one)
    objects.communicationLog && objects.hostPromoter && {
      sourceObjectId: objects.communicationLog.id,
      targetObjectId: objects.hostPromoter.id,
      fieldName: 'hostPromoter',
      fieldLabel: 'Host / Promoter',
      targetFieldLabel: 'Communications',
      targetFieldIcon: 'IconMessage',
    },
    // Communication Log → Concierge Contact (many-to-one)
    objects.communicationLog && objects.conciergeContact && {
      sourceObjectId: objects.communicationLog.id,
      targetObjectId: objects.conciergeContact.id,
      fieldName: 'conciergeContact',
      fieldLabel: 'Concierge Contact',
      targetFieldLabel: 'Communications',
      targetFieldIcon: 'IconMessage',
    },
  ].filter(Boolean);

  for (const rel of relations) {
    try {
      await createRelation(rel);
    } catch (err) {
      console.error(`\n    ✗ FAILED relation "${rel.fieldLabel}": ${err.message}\n`);
    }
  }

  // ── Phase 4: Create Pipelines (Kanban Views) ─────────────────────────────

  console.log('\nPHASE 4: Creating pipelines (Kanban views)...\n');

  // 1. Booking Pipeline on Table Bookings — group by bookingStatus
  const bookingStatusFieldId = fields.tableBooking?.bookingStatus?.id;
  if (objects.tableBooking && bookingStatusFieldId) {
    console.log('  → Booking Pipeline');
    try {
      const bookingView = await createView({
        objectMetadataId: objects.tableBooking.id,
        name: 'Booking Pipeline',
        type: 'KANBAN',
        icon: 'IconLayoutKanban',
        mainGroupByFieldMetadataId: bookingStatusFieldId,
        position: 1,
      });
      await createManyViewGroups(bookingView.id, [
        { fieldValue: 'INQUIRY' },
        { fieldValue: 'DEPOSIT_RECEIVED' },
        { fieldValue: 'CONFIRMED' },
        { fieldValue: 'NIGHT_OF' },
        { fieldValue: 'COMPLETED' },
        { fieldValue: 'NO_SHOW' },
        { fieldValue: 'CANCELLED' },
      ]);
    } catch (err) {
      console.error(`  ✗ Booking Pipeline: ${err.message}`);
    }
  } else {
    console.warn('  ⚠ Skipping Booking Pipeline — tableBooking object or bookingStatus field not available');
  }

  // 2. VIP Relationship Pipeline on VIP Guests — group by relationshipStage
  const relationshipStageFieldId = fields.vipGuest?.relationshipStage?.id;
  if (objects.vipGuest && relationshipStageFieldId) {
    console.log('\n  → VIP Relationship Pipeline');
    try {
      const vipView = await createView({
        objectMetadataId: objects.vipGuest.id,
        name: 'VIP Relationship Pipeline',
        type: 'KANBAN',
        icon: 'IconLayoutKanban',
        mainGroupByFieldMetadataId: relationshipStageFieldId,
        position: 1,
      });
      await createManyViewGroups(vipView.id, [
        { fieldValue: 'NEW_GUEST' },
        { fieldValue: 'ONE_TIME' },
        { fieldValue: 'RETURNING' },
        { fieldValue: 'VIP_REGULAR' },
        { fieldValue: 'VVIP' },
        { fieldValue: 'WHALE' },
      ]);
    } catch (err) {
      console.error(`  ✗ VIP Relationship Pipeline: ${err.message}`);
    }
  } else {
    console.warn('  ⚠ Skipping VIP Relationship Pipeline — vipGuest object or relationshipStage field not available');
  }

  // 3. Concierge Relationship Pipeline on Concierge Contacts — group by conciergeStage
  const conciergeStageFieldId = fields.conciergeContact?.conciergeStage?.id;
  if (objects.conciergeContact && conciergeStageFieldId) {
    console.log('\n  → Concierge Relationship Pipeline');
    try {
      const conciergeView = await createView({
        objectMetadataId: objects.conciergeContact.id,
        name: 'Concierge Relationship Pipeline',
        type: 'KANBAN',
        icon: 'IconLayoutKanban',
        mainGroupByFieldMetadataId: conciergeStageFieldId,
        position: 1,
      });
      await createManyViewGroups(conciergeView.id, [
        { fieldValue: 'COLD' },
        { fieldValue: 'WARM' },
        { fieldValue: 'PRIORITY' },
        { fieldValue: 'STRATEGIC_PARTNER' },
      ]);
    } catch (err) {
      console.error(`  ✗ Concierge Relationship Pipeline: ${err.message}`);
    }
  } else {
    console.warn('  ⚠ Skipping Concierge Pipeline — conciergeContact object or conciergeStage field not available');
  }

  // ── Summary ──────────────────────────────────────────────────────────────

  console.log('\n═══════════════════════════════════════════════════════════');
  console.log('  Setup complete!');
  console.log('═══════════════════════════════════════════════════════════');
  console.log('\nVerification checklist:');
  console.log('  1. Open Twenty → Settings → Data model');
  console.log('     Confirm all 7 objects appear: VIP Guests, Hosts/Promoters,');
  console.log('     Concierge Contacts, Table Bookings, Bottle Orders,');
  console.log('     Events/Nights, Communication Logs');
  console.log('  2. Open each object — verify all fields are present');
  console.log('  3. Open Table Bookings → check for related VIP Guest,');
  console.log('     Host/Promoter, Concierge, Event sections');
  console.log('  4. Open each object\'s view switcher — confirm Kanban pipelines');
  console.log('     appear with correct stage columns');
  console.log('\nObjects summary:');
  for (const [key, obj] of Object.entries(objects)) {
    console.log(`  ${obj ? '✓' : '✗'} ${key}: ${obj?.id ?? 'FAILED'}`);
  }
}

main().catch((err) => {
  console.error('\n\nFATAL ERROR:', err.message);
  process.exit(1);
});

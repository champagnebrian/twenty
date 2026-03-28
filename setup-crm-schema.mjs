#!/usr/bin/env node
// setup-crm-schema.mjs
// Builds a complete nightclub/hospitality CRM schema in Twenty via Metadata API
// Run with: node setup-crm-schema.mjs

const BASE_URL = 'https://ant-silver-rhino.twenty.com';
const API_KEY =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyOTYyZTM0Mi1kNDVjLTRiN2YtODdkOS1mNmE0NDhkMzE3NWYiLCJ0eXBlIjoiQVBJX0tFWSIsIndvcmtzcGFjZUlkIjoiMjk2MmUzNDItZDQ1Yy00YjdmLTg3ZDktZjZhNDQ4ZDMxNzVmIiwiaWF0IjoxNzc0Njg5MTI1LCJleHAiOjQ5MjgyOTI3MjQsImp0aSI6IjNjNmFmOTJkLTM0ZWQtNDQwMS04Y2ExLTZhOTBiYWUyM2U5NSJ9.KQhUTVy2J7wie9EMk_XiXMB4VkgXxTgpYw-ghSDBE0E';

// ─── Helpers ──────────────────────────────────────────────────────────────────

const COLORS = [
  'green', 'turquoise', 'sky', 'blue', 'purple',
  'pink', 'red', 'orange', 'yellow', 'gray',
];
const color = (i) => COLORS[i % COLORS.length];

// Convert a human-readable label into a valid GraphQL enum value
function opts(labels) {
  return labels.map((label, i) => ({
    value: label
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, '_')
      .replace(/^_|_$/g, '')
      .replace(/^\d/, 'N$&'), // prefix leading digit with N
    label,
    color: color(i),
    position: i,
  }));
}

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

  if (json.errors) {
    const msg = json.errors.map((e) => e.message).join('\n');
    throw new Error(msg);
  }

  return json.data;
}

async function createObject(obj) {
  console.log(`\n[Object] Creating "${obj.labelSingular}"...`);
  const data = await metadataRequest(
    `mutation CreateOneObjectMetadataItem($input: CreateOneObjectInput!) {
      createOneObject(input: $input) { id nameSingular labelSingular }
    }`,
    { input: { object: obj } },
  );
  const created = data.createOneObject;
  console.log(`  ✓ ${created.labelSingular}  id: ${created.id}`);
  return created;
}

async function createField(field) {
  process.stdout.write(`  [field] ${field.label} (${field.type}) ... `);
  try {
    const data = await metadataRequest(
      `mutation CreateOneFieldMetadataItem($input: CreateOneFieldMetadataInput!) {
        createOneField(input: $input) { id name label type }
      }`,
      { input: { field } },
    );
    const f = data.createOneField;
    console.log(`✓ (${f.id})`);
    return f;
  } catch (err) {
    console.log(`✗ ERROR: ${err.message}`);
    return null;
  }
}

async function createRelation({
  sourceObjectId,
  targetObjectId,
  fieldName,
  fieldLabel,
  targetFieldLabel,
  targetFieldIcon = 'IconList',
}) {
  process.stdout.write(`  [relation] ${fieldLabel} → ${targetFieldLabel} ... `);
  try {
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
    const f = data.createOneField;
    console.log(`✓ (${f.id})`);
    return f;
  } catch (err) {
    console.log(`✗ ERROR: ${err.message}`);
    return null;
  }
}

async function createView(view) {
  process.stdout.write(`  [view] ${view.name} (${view.type}) ... `);
  try {
    const data = await metadataRequest(
      `mutation CreateView($input: CreateViewInput!) {
        createView(input: $input) { id name type }
      }`,
      { input: view },
    );
    const v = data.createView;
    console.log(`✓ (${v.id})`);
    return v;
  } catch (err) {
    console.log(`✗ ERROR: ${err.message}`);
    return null;
  }
}

async function createManyViewGroups(inputs) {
  try {
    const data = await metadataRequest(
      `mutation CreateManyViewGroups($inputs: [CreateViewGroupInput!]!) {
        createManyViewGroups(inputs: $inputs) { id fieldValue position }
      }`,
      { inputs },
    );
    const groups = data.createManyViewGroups;
    groups.forEach((g) => console.log(`    ✓ stage: ${g.fieldValue}`));
    return groups;
  } catch (err) {
    console.log(`    ✗ ERROR creating view groups: ${err.message}`);
    return [];
  }
}

// ─── Object Definitions ───────────────────────────────────────────────────────

const OBJECTS = [
  {
    key: 'vipGuest',
    nameSingular: 'vipGuest',
    namePlural: 'vipGuests',
    labelSingular: 'VIP Guest',
    labelPlural: 'VIP Guests',
    icon: 'IconStar',
    description: 'High-value nightclub guests',
  },
  {
    key: 'hostPromoter',
    nameSingular: 'hostPromoter',
    namePlural: 'hostPromoters',
    labelSingular: 'Host Promoter',
    labelPlural: 'Hosts and Promoters',
    icon: 'IconUser',
    description: 'In-house hosts, independent promoters, and external agencies',
  },
  {
    key: 'conciergeContact',
    nameSingular: 'conciergeContact',
    namePlural: 'conciergeContacts',
    labelSingular: 'Concierge Contact',
    labelPlural: 'Concierge and FDL Contacts',
    icon: 'IconBuildingHotel',
    description: 'Hotel concierge and FDL contacts who send guests',
  },
  {
    key: 'tableBooking',
    nameSingular: 'tableBooking',
    namePlural: 'tableBookings',
    labelSingular: 'Table Booking',
    labelPlural: 'Table Bookings',
    icon: 'IconTable',
    description: 'Nightclub table reservation records',
  },
  {
    key: 'bottleOrder',
    nameSingular: 'bottleOrder',
    namePlural: 'bottleOrders',
    labelSingular: 'Bottle Order',
    labelPlural: 'Bottle Orders',
    icon: 'IconBottle',
    description: 'Individual bottle line items within a table booking',
  },
  {
    key: 'eventNight',
    nameSingular: 'eventNight',
    namePlural: 'eventNights',
    labelSingular: 'Event Night',
    labelPlural: 'Events and Nights',
    icon: 'IconCalendarEvent',
    description: 'Nightly events and special occasions',
  },
  {
    key: 'communicationLog',
    nameSingular: 'communicationLog',
    namePlural: 'communicationLogs',
    labelSingular: 'Communication Log',
    labelPlural: 'Communication Logs',
    icon: 'IconMessage',
    description: 'All outreach and inbound communication records',
  },
];

// ─── Field Definitions per Object ─────────────────────────────────────────────

function vipGuestFields(objectMetadataId) {
  return [
    // Contact
    { objectMetadataId, name: 'phones', label: 'Phones', type: 'PHONES', isNullable: true },
    { objectMetadataId, name: 'email', label: 'Email', type: 'EMAILS', isNullable: true },
    { objectMetadataId, name: 'instagramHandle', label: 'Instagram Handle', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'address', label: 'Address', type: 'ADDRESS', isNullable: true },
    { objectMetadataId, name: 'profilePhoto', label: 'Profile Photo', type: 'FILES', isNullable: true },
    // Profile
    { objectMetadataId, name: 'nationality', label: 'Nationality', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'languagePreference', label: 'Language Preference', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'dateOfBirth', label: 'Date of Birth', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'birthdayMonth', label: 'Birthday Month', type: 'NUMBER', isNullable: true },
    // Classification
    {
      objectMetadataId, name: 'hotelResidency', label: 'Hotel Residency', type: 'SELECT', isNullable: true,
      options: opts(['Cosmopolitan', 'Wynn', 'Aria', 'Bellagio', 'MGM', 'Venetian', 'Encore', 'Other']),
    },
    {
      objectMetadataId, name: 'tier', label: 'Tier', type: 'SELECT', isNullable: true,
      options: opts(['Bronze', 'Silver', 'Gold', 'VIP', 'VVIP', 'Whale']),
    },
    {
      objectMetadataId, name: 'tags', label: 'Tags', type: 'MULTI_SELECT', isNullable: true,
      options: opts([
        'Celebrity', 'Athlete', 'VVIP', 'Millionaire', 'Billionaire', 'Industry',
        'Local', 'Bachelor Party', 'Bachelorette', 'Wedding', 'Boys Trip',
        'Birthday', 'Conference', 'Hotel Guest', 'FDL',
      ]),
    },
    {
      objectMetadataId, name: 'guestOrigin', label: 'Guest Origin', type: 'SELECT', isNullable: true,
      options: opts(['Host Referral', 'Lead', 'Concierge', 'FDL', 'Referral', 'Walk-Up']),
    },
    // Spend metrics
    { objectMetadataId, name: 'lifetimeTotalSpend', label: 'Lifetime Total Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'averageSpendPerVisit', label: 'Average Spend Per Visit', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'averagePctOverMinimum', label: 'Average Pct Over Minimum', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'visitCount', label: 'Visit Count', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'prestigeBottleSpend', label: 'Prestige Bottle Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'standardBottleSpend', label: 'Standard Bottle Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'addOnSpend', label: 'Add-On Spend', type: 'CURRENCY', isNullable: true },
    {
      objectMetadataId, name: 'milestoneTier', label: 'Milestone Tier', type: 'SELECT', isNullable: true,
      options: opts(['First Visit', '$10K Club', '$50K Club', '$100K Club', '$250K+']),
    },
    // Preferences
    { objectMetadataId, name: 'preferredSection', label: 'Preferred Section', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'preferredTableNumber', label: 'Preferred Table Number', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'bottlePreferences', label: 'Bottle Preferences', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'specialNotes', label: 'Special Notes', type: 'TEXT', isNullable: true },
    // Reliability
    { objectMetadataId, name: 'noShowCount', label: 'No-Show Count', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'cancellationCount', label: 'Cancellation Count', type: 'NUMBER', isNullable: true },
    {
      objectMetadataId, name: 'reliabilityFlag', label: 'Reliability Flag', type: 'SELECT', isNullable: true,
      options: opts(['Reliable', 'Watch', 'Unreliable']),
    },
    // Dates
    { objectMetadataId, name: 'firstVisitDate', label: 'First Visit Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'lastVisitDate', label: 'Last Visit Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'lastContactDate', label: 'Last Contact Date', type: 'DATE', isNullable: true },
    // Blacklist
    { objectMetadataId, name: 'blacklisted', label: 'Blacklisted', type: 'BOOLEAN', isNullable: true },
    {
      objectMetadataId, name: 'blacklistReason', label: 'Blacklist Reason', type: 'SELECT', isNullable: true,
      options: opts(['Chargeback', 'Violence', 'Theft', 'Behavior', 'Management Ban']),
    },
    { objectMetadataId, name: 'blacklistDate', label: 'Blacklist Date', type: 'DATE', isNullable: true },
    // Flags & alerts
    { objectMetadataId, name: 'flaggedForReview', label: 'Flagged For Review', type: 'BOOLEAN', isNullable: true },
    { objectMetadataId, name: 'alertNote', label: 'Alert Note', type: 'TEXT', isNullable: true },
    // Sentiment & follow-up
    {
      objectMetadataId, name: 'guestSentiment', label: 'Guest Sentiment', type: 'SELECT', isNullable: true,
      options: opts(['5-Star', '4-Star', '3-Star', 'Had Issues']),
    },
    { objectMetadataId, name: 'followUpDate', label: 'Follow-Up Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'followUpNote', label: 'Follow-Up Note', type: 'TEXT', isNullable: true },
    // Status
    {
      objectMetadataId, name: 'status', label: 'Status', type: 'SELECT', isNullable: true,
      options: opts(['Active', 'Dormant', 'Blacklisted']),
    },
    // Pipeline stage — used as the group-by field for VIP Relationship Pipeline
    {
      objectMetadataId, name: 'relationshipStage', label: 'Relationship Stage', type: 'SELECT', isNullable: true,
      options: opts(['New Guest', 'One-Time', 'Returning', 'VIP Regular', 'VVIP', 'Whale']),
    },
  ];
}

function hostPromoterFields(objectMetadataId) {
  return [
    { objectMetadataId, name: 'phones', label: 'Phones', type: 'PHONES', isNullable: true },
    { objectMetadataId, name: 'email', label: 'Email', type: 'EMAILS', isNullable: true },
    { objectMetadataId, name: 'instagramHandle', label: 'Instagram Handle', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'mailingAddress', label: 'Mailing Address', type: 'ADDRESS', isNullable: true },
    { objectMetadataId, name: 'profilePhoto', label: 'Profile Photo', type: 'FILES', isNullable: true },
    {
      objectMetadataId, name: 'hostType', label: 'Type', type: 'SELECT', isNullable: true,
      options: opts(['In-House Host', 'Independent Promoter', 'External Agency', 'Concierge', 'FDL']),
    },
    { objectMetadataId, name: 'totalClientsReferred', label: 'Total Clients Referred', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'totalRevenueAttributed', label: 'Total Revenue Attributed', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'averageClientSpend', label: 'Average Client Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'averageClientPctOverMinimum', label: 'Average Client Pct Over Minimum', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'commissionRate', label: 'Commission Rate', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'compValueOwed', label: 'Comp Value Owed', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'followUpDate', label: 'Follow-Up Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'followUpNote', label: 'Follow-Up Note', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'lastContactDate', label: 'Last Contact Date', type: 'DATE', isNullable: true },
    {
      objectMetadataId, name: 'status', label: 'Status', type: 'SELECT', isNullable: true,
      options: opts(['Active', 'Inactive']),
    },
  ];
}

function conciergeContactFields(objectMetadataId) {
  return [
    { objectMetadataId, name: 'phones', label: 'Phones', type: 'PHONES', isNullable: true },
    { objectMetadataId, name: 'email', label: 'Email', type: 'EMAILS', isNullable: true },
    { objectMetadataId, name: 'instagramHandle', label: 'Instagram Handle', type: 'TEXT', isNullable: true },
    {
      objectMetadataId, name: 'hotelCompany', label: 'Hotel Company', type: 'SELECT', isNullable: true,
      options: opts(['Cosmopolitan', 'Wynn', 'Aria', 'Bellagio', 'MGM', 'Venetian', 'Encore', 'Independent']),
    },
    { objectMetadataId, name: 'roleTitle', label: 'Role Title', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'totalGuestsSent', label: 'Total Guests Sent', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'totalRevenueGenerated', label: 'Total Revenue Generated', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'averageGuestSpend', label: 'Average Guest Spend', type: 'CURRENCY', isNullable: true },
    {
      objectMetadataId, name: 'relationshipQuality', label: 'Relationship Quality', type: 'SELECT', isNullable: true,
      options: opts(['Priority', 'Warm', 'Cold', 'Inactive']),
    },
    { objectMetadataId, name: 'lastOutreachDate', label: 'Last Outreach Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'followUpDate', label: 'Follow-Up Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'followUpNote', label: 'Follow-Up Note', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'notes', label: 'Notes', type: 'TEXT', isNullable: true },
    // Pipeline stage — used as the group-by field for Concierge Relationship Pipeline
    {
      objectMetadataId, name: 'conciergeStage', label: 'Concierge Stage', type: 'SELECT', isNullable: true,
      options: opts(['Cold', 'Warm', 'Priority', 'Strategic Partner']),
    },
  ];
}

function tableBookingFields(objectMetadataId) {
  return [
    { objectMetadataId, name: 'bookingName', label: 'Booking Name', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'bookingDate', label: 'Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'tableNumber', label: 'Table Number', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'section', label: 'Section', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'partySize', label: 'Party Size', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'minimumSpend', label: 'Minimum Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'actualSpend', label: 'Actual Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'dollarOverMinimum', label: 'Dollar Over Minimum', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'percentOverMinimum', label: 'Percent Over Minimum', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'prestigeBottleSpend', label: 'Prestige Bottle Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'standardBottleSpend', label: 'Standard Bottle Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'addOnSpend', label: 'Add-On Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'compItems', label: 'Comp Items', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'compValue', label: 'Comp Value', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'netRevenue', label: 'Net Revenue', type: 'CURRENCY', isNullable: true },
    {
      objectMetadataId, name: 'paymentMethod', label: 'Payment Method', type: 'SELECT', isNullable: true,
      options: opts(['Card', 'Cash', 'Comped', 'Split']),
    },
    // Used as the group-by field for the Booking Pipeline kanban view
    {
      objectMetadataId, name: 'bookingStatus', label: 'Booking Status', type: 'SELECT', isNullable: true,
      options: opts(['Inquiry', 'Deposit Received', 'Confirmed', 'Night Of', 'Completed', 'No-Show', 'Cancelled']),
    },
    {
      objectMetadataId, name: 'guestSentiment', label: 'Guest Sentiment', type: 'SELECT', isNullable: true,
      options: opts(['5-Star', '4-Star', '3-Star', 'Had Issues']),
    },
    { objectMetadataId, name: 'issueNotes', label: 'Issue Notes', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'specialRequests', label: 'Special Requests', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'postVisitFollowUpDate', label: 'Post-Visit Follow-Up Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'followUpNote', label: 'Follow-Up Note', type: 'TEXT', isNullable: true },
  ];
}

function bottleOrderFields(objectMetadataId) {
  return [
    { objectMetadataId, name: 'bottleName', label: 'Bottle Name', type: 'TEXT', isNullable: true },
    {
      objectMetadataId, name: 'category', label: 'Category', type: 'SELECT', isNullable: true,
      options: opts(['Champagne', 'Vodka', 'Tequila', 'Whiskey', 'Cognac', 'Add-On', 'Experience']),
    },
    { objectMetadataId, name: 'brand', label: 'Brand', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'quantity', label: 'Quantity', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'pricePerBottle', label: 'Price Per Bottle', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'lineTotal', label: 'Line Total', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'comped', label: 'Comped', type: 'BOOLEAN', isNullable: true },
    { objectMetadataId, name: 'compValue', label: 'Comp Value', type: 'CURRENCY', isNullable: true },
  ];
}

function eventNightFields(objectMetadataId) {
  return [
    { objectMetadataId, name: 'eventName', label: 'Event Name', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'eventDate', label: 'Date', type: 'DATE', isNullable: true },
    { objectMetadataId, name: 'dayOfWeek', label: 'Day of Week', type: 'TEXT', isNullable: true },
    {
      objectMetadataId, name: 'eventType', label: 'Type', type: 'SELECT', isNullable: true,
      options: opts(['DJ Night', 'Special Event', 'Holiday', 'Buyout', 'Residency']),
    },
    { objectMetadataId, name: 'expectedCapacity', label: 'Expected Capacity', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'totalTablesAvailable', label: 'Total Tables Available', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'notes', label: 'Notes', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'totalBookings', label: 'Total Bookings', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'totalRevenue', label: 'Total Revenue', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'averageTableSpend', label: 'Average Table Spend', type: 'CURRENCY', isNullable: true },
    { objectMetadataId, name: 'averagePctOverMinimum', label: 'Average Pct Over Minimum', type: 'NUMBER', isNullable: true },
    { objectMetadataId, name: 'noShowCount', label: 'No-Show Count', type: 'NUMBER', isNullable: true },
  ];
}

function communicationLogFields(objectMetadataId) {
  return [
    { objectMetadataId, name: 'dateAndTime', label: 'Date and Time', type: 'DATE_TIME', isNullable: true },
    {
      objectMetadataId, name: 'channel', label: 'Channel', type: 'SELECT', isNullable: true,
      options: opts(['SMS', 'Call', 'Instagram DM', 'In-Person']),
    },
    {
      objectMetadataId, name: 'direction', label: 'Direction', type: 'SELECT', isNullable: true,
      options: opts(['Outbound', 'Inbound']),
    },
    { objectMetadataId, name: 'summary', label: 'Summary', type: 'TEXT', isNullable: true },
    { objectMetadataId, name: 'followUpRequired', label: 'Follow-Up Required', type: 'BOOLEAN', isNullable: true },
  ];
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  console.log('═══════════════════════════════════════════════════');
  console.log('  Twenty CRM – Nightclub Schema Builder');
  console.log('═══════════════════════════════════════════════════\n');

  // ── Phase 1: Create Objects ─────────────────────────────────────────────
  console.log('▶ PHASE 1: Creating Objects\n');

  const ids = {};
  for (const obj of OBJECTS) {
    const { key, ...input } = obj;
    const created = await createObject(input);
    ids[key] = created.id;
  }

  console.log('\n✅ All objects created.\n');

  // ── Phase 2: Create Fields ──────────────────────────────────────────────
  console.log('▶ PHASE 2: Creating Fields\n');

  const fieldIds = {};

  async function addFields(key, fields) {
    console.log(`\n  ── ${key} ──`);
    fieldIds[key] = {};
    for (const f of fields) {
      const created = await createField(f);
      if (created) fieldIds[key][f.name] = created.id;
    }
  }

  await addFields('vipGuest', vipGuestFields(ids.vipGuest));
  await addFields('hostPromoter', hostPromoterFields(ids.hostPromoter));
  await addFields('conciergeContact', conciergeContactFields(ids.conciergeContact));
  await addFields('tableBooking', tableBookingFields(ids.tableBooking));
  await addFields('bottleOrder', bottleOrderFields(ids.bottleOrder));
  await addFields('eventNight', eventNightFields(ids.eventNight));
  await addFields('communicationLog', communicationLogFields(ids.communicationLog));

  console.log('\n✅ All fields created.\n');

  // ── Phase 3: Create Relationships ──────────────────────────────────────
  console.log('▶ PHASE 3: Creating Relationships\n');

  const relations = [
    // VIP Guest → Referred By → Host/Promoter
    {
      sourceObjectId: ids.vipGuest,
      targetObjectId: ids.hostPromoter,
      fieldName: 'referredBy',
      fieldLabel: 'Referred By',
      targetFieldLabel: 'Referred VIP Guests',
      targetFieldIcon: 'IconUsers',
    },
    // VIP Guest → Host Owner → Host/Promoter
    {
      sourceObjectId: ids.vipGuest,
      targetObjectId: ids.hostPromoter,
      fieldName: 'hostOwner',
      fieldLabel: 'Host Owner',
      targetFieldLabel: 'Owned VIP Guests',
      targetFieldIcon: 'IconUsers',
    },
    // VIP Guest → Referral Chain (self many-to-one)
    {
      sourceObjectId: ids.vipGuest,
      targetObjectId: ids.vipGuest,
      fieldName: 'referralSource',
      fieldLabel: 'Referral Source',
      targetFieldLabel: 'Referred Guests',
      targetFieldIcon: 'IconGitMerge',
    },
    // VIP Guest → Known Associates (self, first direction; approximates many-to-many)
    {
      sourceObjectId: ids.vipGuest,
      targetObjectId: ids.vipGuest,
      fieldName: 'knownAssociate',
      fieldLabel: 'Known Associate',
      targetFieldLabel: 'Associated With',
      targetFieldIcon: 'IconUsersGroup',
    },
    // Table Booking → VIP Guest
    {
      sourceObjectId: ids.tableBooking,
      targetObjectId: ids.vipGuest,
      fieldName: 'vipGuest',
      fieldLabel: 'VIP Guest',
      targetFieldLabel: 'Table Bookings',
      targetFieldIcon: 'IconTable',
    },
    // Table Booking → Host/Promoter
    {
      sourceObjectId: ids.tableBooking,
      targetObjectId: ids.hostPromoter,
      fieldName: 'hostPromoter',
      fieldLabel: 'Host Promoter',
      targetFieldLabel: 'Table Bookings',
      targetFieldIcon: 'IconTable',
    },
    // Table Booking → Concierge Contact
    {
      sourceObjectId: ids.tableBooking,
      targetObjectId: ids.conciergeContact,
      fieldName: 'conciergeContact',
      fieldLabel: 'Concierge Contact',
      targetFieldLabel: 'Table Bookings',
      targetFieldIcon: 'IconTable',
    },
    // Table Booking → Event/Night
    {
      sourceObjectId: ids.tableBooking,
      targetObjectId: ids.eventNight,
      fieldName: 'eventNight',
      fieldLabel: 'Event Night',
      targetFieldLabel: 'Table Bookings',
      targetFieldIcon: 'IconTable',
    },
    // Bottle Order → Table Booking
    {
      sourceObjectId: ids.bottleOrder,
      targetObjectId: ids.tableBooking,
      fieldName: 'tableBooking',
      fieldLabel: 'Table Booking',
      targetFieldLabel: 'Bottle Orders',
      targetFieldIcon: 'IconBottle',
    },
    // Communication Log → VIP Guest
    {
      sourceObjectId: ids.communicationLog,
      targetObjectId: ids.vipGuest,
      fieldName: 'vipGuest',
      fieldLabel: 'VIP Guest',
      targetFieldLabel: 'Communication Logs',
      targetFieldIcon: 'IconMessage',
    },
    // Communication Log → Host/Promoter
    {
      sourceObjectId: ids.communicationLog,
      targetObjectId: ids.hostPromoter,
      fieldName: 'hostPromoter',
      fieldLabel: 'Host Promoter',
      targetFieldLabel: 'Communication Logs',
      targetFieldIcon: 'IconMessage',
    },
    // Communication Log → Concierge Contact
    {
      sourceObjectId: ids.communicationLog,
      targetObjectId: ids.conciergeContact,
      fieldName: 'conciergeContact',
      fieldLabel: 'Concierge Contact',
      targetFieldLabel: 'Communication Logs',
      targetFieldIcon: 'IconMessage',
    },
  ];

  for (const rel of relations) {
    await createRelation(rel);
  }

  console.log('\n✅ All relationships created.\n');

  // ── Phase 4: Create Pipelines (Kanban Views + Stages) ──────────────────
  console.log('▶ PHASE 4: Creating Pipelines\n');

  // Pipeline 1: Booking Pipeline → tableBooking.bookingStatus
  const bookingStatusFieldId = fieldIds?.tableBooking?.bookingStatus;
  if (bookingStatusFieldId) {
    console.log('\n  → Booking Pipeline');
    const bookingView = await createView({
      name: 'Booking Pipeline',
      objectMetadataId: ids.tableBooking,
      type: 'KANBAN',
      icon: 'IconLayoutKanban',
      position: 1,
      mainGroupByFieldMetadataId: bookingStatusFieldId,
    });
    if (bookingView) {
      const stages = opts([
        'Inquiry', 'Deposit Received', 'Confirmed',
        'Night Of', 'Completed', 'No-Show', 'Cancelled',
      ]);
      await createManyViewGroups(
        stages.map((s) => ({
          viewId: bookingView.id,
          fieldValue: s.value,
          position: s.position,
          isVisible: true,
        })),
      );
    }
  } else {
    console.log('  ⚠ Skipping Booking Pipeline: bookingStatus field ID not found');
  }

  // Pipeline 2: VIP Relationship Pipeline → vipGuest.relationshipStage
  const relationshipStageFieldId = fieldIds?.vipGuest?.relationshipStage;
  if (relationshipStageFieldId) {
    console.log('\n  → VIP Relationship Pipeline');
    const vipView = await createView({
      name: 'VIP Relationship Pipeline',
      objectMetadataId: ids.vipGuest,
      type: 'KANBAN',
      icon: 'IconLayoutKanban',
      position: 1,
      mainGroupByFieldMetadataId: relationshipStageFieldId,
    });
    if (vipView) {
      const stages = opts([
        'New Guest', 'One-Time', 'Returning',
        'VIP Regular', 'VVIP', 'Whale',
      ]);
      await createManyViewGroups(
        stages.map((s) => ({
          viewId: vipView.id,
          fieldValue: s.value,
          position: s.position,
          isVisible: true,
        })),
      );
    }
  } else {
    console.log('  ⚠ Skipping VIP Relationship Pipeline: relationshipStage field ID not found');
  }

  // Pipeline 3: Concierge Relationship Pipeline → conciergeContact.conciergeStage
  const conciergeStageFieldId = fieldIds?.conciergeContact?.conciergeStage;
  if (conciergeStageFieldId) {
    console.log('\n  → Concierge Relationship Pipeline');
    const conciergeView = await createView({
      name: 'Concierge Relationship Pipeline',
      objectMetadataId: ids.conciergeContact,
      type: 'KANBAN',
      icon: 'IconLayoutKanban',
      position: 1,
      mainGroupByFieldMetadataId: conciergeStageFieldId,
    });
    if (conciergeView) {
      const stages = opts(['Cold', 'Warm', 'Priority', 'Strategic Partner']);
      await createManyViewGroups(
        stages.map((s) => ({
          viewId: conciergeView.id,
          fieldValue: s.value,
          position: s.position,
          isVisible: true,
        })),
      );
    }
  } else {
    console.log('  ⚠ Skipping Concierge Pipeline: conciergeStage field ID not found');
  }

  // ── Summary ─────────────────────────────────────────────────────────────
  console.log('\n═══════════════════════════════════════════════════');
  console.log('  DONE — Schema build complete!');
  console.log('═══════════════════════════════════════════════════');
  console.log('\nCreated Object IDs:');
  for (const [key, id] of Object.entries(ids)) {
    console.log(`  ${key.padEnd(22)} ${id}`);
  }
  console.log('\nVerify at: https://ant-silver-rhino.twenty.com/settings/data-model\n');
}

main().catch((err) => {
  console.error('\n❌ Fatal error:', err.message);
  process.exit(1);
});

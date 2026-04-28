const draftPicks = [
  {
    "pick": 1,
    "team": "LV",
    "player": "Fernando Mendoza",
    "position": "QB",
    "college": "Indiana",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 2,
    "team": "NYJ",
    "player": "David Bailey",
    "position": "EDGE",
    "college": "Texas Tech",
    "team_name": "New York Jets"
  },
  {
    "pick": 3,
    "team": "ARI",
    "player": "Jeremiyah Love",
    "position": "RB",
    "college": "Notre Dame",
    "team_name": "Arizona Cardinals"
  },
  {
    "pick": 4,
    "team": "TEN",
    "player": "Carnell Tate",
    "position": "WR",
    "college": "Ohio State",
    "team_name": "Tennessee Titans"
  },
  {
    "pick": 5,
    "team": "NYG",
    "player": "Arvell Reese",
    "position": "LB/EDGE",
    "college": "Ohio State",
    "team_name": "New York Giants"
  },
  {
    "pick": 6,
    "team": "KC",
    "player": "Mansoor Delane",
    "position": "CB",
    "college": "LSU",
    "team_name": "Kansas City Chiefs"
  },
  {
    "pick": 7,
    "team": "WSH",
    "player": "Sonny Styles",
    "position": "LB",
    "college": "Ohio State",
    "team_name": "WSH"
  },
  {
    "pick": 8,
    "team": "NO",
    "player": "Jordyn Tyson",
    "position": "WR",
    "college": "Arizona State",
    "team_name": "New Orleans Saints"
  },
  {
    "pick": 9,
    "team": "CLE",
    "player": "Spencer Fano",
    "position": "OT",
    "college": "Utah",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 10,
    "team": "NYG",
    "player": "Francis Mauigoa",
    "position": "OT",
    "college": "Miami",
    "team_name": "New York Giants"
  },
  {
    "pick": 11,
    "team": "DAL",
    "player": "Caleb Downs",
    "position": "S",
    "college": "Ohio State",
    "team_name": "Dallas Cowboys"
  },
  {
    "pick": 12,
    "team": "MIA",
    "player": "Kadyn Proctor",
    "position": "OT",
    "college": "Alabama",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 13,
    "team": "LAR",
    "player": "Ty Simpson",
    "position": "QB",
    "college": "Alabama",
    "team_name": "Los Angeles Rams"
  },
  {
    "pick": 14,
    "team": "BAL",
    "player": "Vega Ioane",
    "position": "IOL",
    "college": "Penn State",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 15,
    "team": "TB",
    "player": "Rueben Bain Jr.",
    "position": "EDGE",
    "college": "Miami",
    "team_name": "Tampa Bay Buccaneers"
  },
  {
    "pick": 16,
    "team": "NYJ",
    "player": "Kenyon Sadiq",
    "position": "TE",
    "college": "Oregon",
    "team_name": "New York Jets"
  },
  {
    "pick": 17,
    "team": "DET",
    "player": "Blake Miller",
    "position": "OT",
    "college": "Clemson",
    "team_name": "Detroit Lions"
  },
  {
    "pick": 18,
    "team": "MIN",
    "player": "Caleb Banks",
    "position": "DL",
    "college": "Florida",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 19,
    "team": "CAR",
    "player": "Monroe Freeling",
    "position": "OT",
    "college": "Georgia",
    "team_name": "Carolina Panthers"
  },
  {
    "pick": 20,
    "team": "PHI",
    "player": "Makai Lemon",
    "position": "WR",
    "college": "USC",
    "team_name": "Philadelphia Eagles"
  },
  {
    "pick": 21,
    "team": "PIT",
    "player": "Max Iheanachor",
    "position": "OT",
    "college": "Arizona State",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 22,
    "team": "LAC",
    "player": "Akheem Mesidor",
    "position": "EDGE",
    "college": "Miami",
    "team_name": "Los Angeles Chargers"
  },
  {
    "pick": 23,
    "team": "DAL",
    "player": "Malachi Lawrence",
    "position": "EDGE",
    "college": "UCF",
    "team_name": "Dallas Cowboys"
  },
  {
    "pick": 24,
    "team": "CLE",
    "player": "KC Concepcion",
    "position": "WR",
    "college": "Texas A&M",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 25,
    "team": "CHI",
    "player": "Dillon Thieneman",
    "position": "S",
    "college": "Oregon",
    "team_name": "Chicago Bears"
  },
  {
    "pick": 26,
    "team": "HOU",
    "player": "Keylan Rutledge",
    "position": "IOL",
    "college": "Georgia Tech",
    "team_name": "Houston Texans"
  },
  {
    "pick": 27,
    "team": "MIA",
    "player": "Chris Johnson",
    "position": "CB",
    "college": "San Diego State",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 28,
    "team": "NE",
    "player": "Caleb Lomu",
    "position": "OT",
    "college": "Utah",
    "team_name": "New England Patriots"
  },
  {
    "pick": 29,
    "team": "KC",
    "player": "Peter Woods",
    "position": "DL",
    "college": "Clemson",
    "team_name": "Kansas City Chiefs"
  },
  {
    "pick": 30,
    "team": "NYJ",
    "player": "Omar Cooper Jr.",
    "position": "WR",
    "college": "Indiana",
    "team_name": "New York Jets"
  },
  {
    "pick": 31,
    "team": "TEN",
    "player": "Keldric Faulk",
    "position": "EDGE",
    "college": "Auburn",
    "team_name": "Tennessee Titans"
  },
  {
    "pick": 32,
    "team": "SEA",
    "player": "Jadarian Price",
    "position": "RB",
    "college": "Notre Dame",
    "team_name": "Seattle Seahawks"
  },
  {
    "pick": 33,
    "team": "SF",
    "player": "De'Zhaun Stribling",
    "position": "WR",
    "college": "Ole Miss",
    "team_name": "San Francisco 49ers"
  },
  {
    "pick": 34,
    "team": "ARI",
    "player": "Chase Bisontis",
    "position": "IOL",
    "college": "Texas A&M",
    "team_name": "Arizona Cardinals"
  },
  {
    "pick": 35,
    "team": "BUF",
    "player": "T.J. Parker",
    "position": "EDGE",
    "college": "Clemson",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 36,
    "team": "HOU",
    "player": "Kayden McDonald",
    "position": "DL",
    "college": "Ohio State",
    "team_name": "Houston Texans"
  },
  {
    "pick": 37,
    "team": "NYG",
    "player": "Colton Hood",
    "position": "CB",
    "college": "Tennessee",
    "team_name": "New York Giants"
  },
  {
    "pick": 38,
    "team": "LV",
    "player": "Treydan Stukes",
    "position": "CB",
    "college": "Arizona",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 39,
    "team": "CLE",
    "player": "Denzel Boston",
    "position": "WR",
    "college": "Washington",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 40,
    "team": "KC",
    "player": "R Mason Thomas",
    "position": "EDGE",
    "college": "Oklahoma",
    "team_name": "Kansas City Chiefs"
  },
  {
    "pick": 41,
    "team": "CIN",
    "player": "Cashius Howell",
    "position": "EDGE",
    "college": "Texas A&M",
    "team_name": "Cincinnati Bengals"
  },
  {
    "pick": 42,
    "team": "NO",
    "player": "Christen Miller",
    "position": "DL",
    "college": "Georgia",
    "team_name": "New Orleans Saints"
  },
  {
    "pick": 43,
    "team": "MIA",
    "player": "Jacob Rodriguez",
    "position": "LB",
    "college": "Texas Tech",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 44,
    "team": "DET",
    "player": "Derrick Moore",
    "position": "EDGE",
    "college": "Michigan",
    "team_name": "Detroit Lions"
  },
  {
    "pick": 45,
    "team": "BAL",
    "player": "Zion Young",
    "position": "EDGE",
    "college": "Missouri",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 46,
    "team": "TB",
    "player": "Josiah Trotter",
    "position": "LB",
    "college": "Missouri",
    "team_name": "Tampa Bay Buccaneers"
  },
  {
    "pick": 47,
    "team": "PIT",
    "player": "Germie Bernard",
    "position": "WR",
    "college": "Alabama",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 48,
    "team": "ATL",
    "player": "Avieon Terrell",
    "position": "CB",
    "college": "Clemson",
    "team_name": "Atlanta Falcons"
  },
  {
    "pick": 49,
    "team": "CAR",
    "player": "Lee Hunter",
    "position": "DL",
    "college": "Texas Tech",
    "team_name": "Carolina Panthers"
  },
  {
    "pick": 50,
    "team": "NYJ",
    "player": "D'Angelo Ponds",
    "position": "CB",
    "college": "Indiana",
    "team_name": "New York Jets"
  },
  {
    "pick": 51,
    "team": "MIN",
    "player": "Jake Golday",
    "position": "LB",
    "college": "Cincinnati",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 52,
    "team": "GB",
    "player": "Brandon Cisse",
    "position": "CB",
    "college": "South Carolina",
    "team_name": "Green Bay Packers"
  },
  {
    "pick": 53,
    "team": "IND",
    "player": "CJ Allen",
    "position": "LB",
    "college": "Georgia",
    "team_name": "Indianapolis Colts"
  },
  {
    "pick": 54,
    "team": "PHI",
    "player": "Eli Stowers",
    "position": "TE",
    "college": "Vanderbilt",
    "team_name": "Philadelphia Eagles"
  },
  {
    "pick": 55,
    "team": "NE",
    "player": "Gabe Jacas",
    "position": "EDGE",
    "college": "Illinois",
    "team_name": "New England Patriots"
  },
  {
    "pick": 56,
    "team": "JAX",
    "player": "Nate Boerkircher",
    "position": "TE",
    "college": "Texas A&M",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 57,
    "team": "CHI",
    "player": "Logan Jones",
    "position": "IOL",
    "college": "Iowa",
    "team_name": "Chicago Bears"
  },
  {
    "pick": 58,
    "team": "CLE",
    "player": "Emmanuel McNeil-Warren",
    "position": "S",
    "college": "Toledo",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 59,
    "team": "HOU",
    "player": "Marlin Klein",
    "position": "TE",
    "college": "Michigan",
    "team_name": "Houston Texans"
  },
  {
    "pick": 60,
    "team": "TEN",
    "player": "Anthony Hill Jr.",
    "position": "LB",
    "college": "Texas",
    "team_name": "Tennessee Titans"
  },
  {
    "pick": 61,
    "team": "LAR",
    "player": "Max Klare",
    "position": "TE",
    "college": "Ohio State",
    "team_name": "Los Angeles Rams"
  },
  {
    "pick": 62,
    "team": "BUF",
    "player": "Davison Igbinosun",
    "position": "CB",
    "college": "Ohio State",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 63,
    "team": "LAC",
    "player": "Jake Slaughter",
    "position": "IOL",
    "college": "Florida",
    "team_name": "Los Angeles Chargers"
  },
  {
    "pick": 64,
    "team": "SEA",
    "player": "Bud Clark",
    "position": "S",
    "college": "TCU",
    "team_name": "Seattle Seahawks"
  },
  {
    "pick": 65,
    "team": "ARI",
    "player": "Carson Beck",
    "position": "QB",
    "college": "Miami",
    "team_name": "Arizona Cardinals"
  },
  {
    "pick": 66,
    "team": "DEN",
    "player": "Tyler Onyedim",
    "position": "DL",
    "college": "Texas A&M",
    "team_name": "Denver Broncos"
  },
  {
    "pick": 67,
    "team": "LV",
    "player": "Keyron Crawford",
    "position": "EDGE",
    "college": "Auburn",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 68,
    "team": "PHI",
    "player": "Markel Bell",
    "position": "OT",
    "college": "Miami",
    "team_name": "Philadelphia Eagles"
  },
  {
    "pick": 69,
    "team": "CHI",
    "player": "Sam Roush",
    "position": "TE",
    "college": "Stanford",
    "team_name": "Chicago Bears"
  },
  {
    "pick": 70,
    "team": "SF",
    "player": "Romello Height",
    "position": "EDGE",
    "college": "Texas Tech",
    "team_name": "San Francisco 49ers"
  },
  {
    "pick": 71,
    "team": "WSH",
    "player": "Antonio Williams",
    "position": "WR",
    "college": "Clemson",
    "team_name": "WSH"
  },
  {
    "pick": 72,
    "team": "CIN",
    "player": "Tacario Davis",
    "position": "CB",
    "college": "Washington",
    "team_name": "Cincinnati Bengals"
  },
  {
    "pick": 73,
    "team": "NO",
    "player": "Oscar Delp",
    "position": "TE",
    "college": "Georgia",
    "team_name": "New Orleans Saints"
  },
  {
    "pick": 74,
    "team": "NYG",
    "player": "Malachi Fields",
    "position": "WR",
    "college": "Notre Dame",
    "team_name": "New York Giants"
  },
  {
    "pick": 75,
    "team": "MIA",
    "player": "Caleb Douglas",
    "position": "WR",
    "college": "Texas Tech",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 76,
    "team": "PIT",
    "player": "Drew Allar",
    "position": "QB",
    "college": "Penn State",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 77,
    "team": "GB",
    "player": "Chris McClellan",
    "position": "DL",
    "college": "Missouri",
    "team_name": "Green Bay Packers"
  },
  {
    "pick": 78,
    "team": "IND",
    "player": "A.J. Haulcy",
    "position": "S",
    "college": "LSU",
    "team_name": "Indianapolis Colts"
  },
  {
    "pick": 79,
    "team": "ATL",
    "player": "Zachariah Branch",
    "position": "WR",
    "college": "Georgia",
    "team_name": "Atlanta Falcons"
  },
  {
    "pick": 80,
    "team": "BAL",
    "player": "Ja'Kobi Lane",
    "position": "WR",
    "college": "USC",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 81,
    "team": "JAX",
    "player": "Albert Regis",
    "position": "DL",
    "college": "Texas A&M",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 82,
    "team": "MIN",
    "player": "Domonique Orange",
    "position": "DL",
    "college": "Iowa State",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 83,
    "team": "CAR",
    "player": "Chris Brazzell II",
    "position": "WR",
    "college": "Tennessee",
    "team_name": "Carolina Panthers"
  },
  {
    "pick": 84,
    "team": "TB",
    "player": "Ted Hurst",
    "position": "WR",
    "college": "Georgia State",
    "team_name": "Tampa Bay Buccaneers"
  },
  {
    "pick": 85,
    "team": "PIT",
    "player": "Daylen Everette",
    "position": "CB",
    "college": "Georgia",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 86,
    "team": "CLE",
    "player": "Austin Barber",
    "position": "OT",
    "college": "Florida",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 87,
    "team": "MIA",
    "player": "Will Kacmarek",
    "position": "TE",
    "college": "Ohio State",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 88,
    "team": "JAX",
    "player": "Emmanuel Pregnon",
    "position": "IOL",
    "college": "Oregon",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 89,
    "team": "CHI",
    "player": "Zavion Thomas",
    "position": "WR",
    "college": "LSU",
    "team_name": "Chicago Bears"
  },
  {
    "pick": 90,
    "team": "SF",
    "player": "Kaelon Black",
    "position": "RB",
    "college": "Indiana",
    "team_name": "San Francisco 49ers"
  },
  {
    "pick": 91,
    "team": "LV",
    "player": "Trey Zuhn III",
    "position": "IOL/OT",
    "college": "Texas A&M",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 92,
    "team": "DAL",
    "player": "Jaishawn Barham",
    "position": "LB",
    "college": "Michigan",
    "team_name": "Dallas Cowboys"
  },
  {
    "pick": 93,
    "team": "LAR",
    "player": "Keagen Trost",
    "position": "OT",
    "college": "Missouri",
    "team_name": "Los Angeles Rams"
  },
  {
    "pick": 94,
    "team": "MIA",
    "player": "Chris Bell",
    "position": "WR",
    "college": "Louisville",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 95,
    "team": "NE",
    "player": "Eli Raridon",
    "position": "TE",
    "college": "Notre Dame",
    "team_name": "New England Patriots"
  },
  {
    "pick": 96,
    "team": "PIT",
    "player": "Gennings Dunker",
    "position": "OT/IOL",
    "college": "Iowa",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 97,
    "team": "MIN",
    "player": "Caleb Tiernan",
    "position": "OT",
    "college": "Northwestern",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 98,
    "team": "MIN",
    "player": "Jakobe Thomas",
    "position": "S",
    "college": "Miami",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 99,
    "team": "SEA",
    "player": "Julian Neal",
    "position": "CB",
    "college": "Arkansas",
    "team_name": "Seattle Seahawks"
  },
  {
    "pick": 100,
    "team": "JAX",
    "player": "Jalen Huskey",
    "position": "S",
    "college": "Maryland",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 101,
    "team": "LV",
    "player": "Jermod McCoy",
    "position": "CB",
    "college": "Tennessee",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 102,
    "team": "BUF",
    "player": "Jude Bowry",
    "position": "OT",
    "college": "Boston College",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 103,
    "team": "NYJ",
    "player": "Darrell Jackson Jr.",
    "position": "DL",
    "college": "Florida State",
    "team_name": "New York Jets"
  },
  {
    "pick": 104,
    "team": "ARI",
    "player": "Kaleb Proctor",
    "position": "DL",
    "college": "Southeastern Louisiana",
    "team_name": "Arizona Cardinals"
  },
  {
    "pick": 105,
    "team": "LAC",
    "player": "Brenen Thompson",
    "position": "WR",
    "college": "Mississippi State",
    "team_name": "Los Angeles Chargers"
  },
  {
    "pick": 106,
    "team": "HOU",
    "player": "Febechi Nwaiwu",
    "position": "IOL",
    "college": "Oklahoma",
    "team_name": "Houston Texans"
  },
  {
    "pick": 107,
    "team": "SF",
    "player": "Gracen Halton",
    "position": "DL",
    "college": "Oklahoma",
    "team_name": "San Francisco 49ers"
  },
  {
    "pick": 108,
    "team": "DEN",
    "player": "Jonah Coleman",
    "position": "RB",
    "college": "Washington",
    "team_name": "Denver Broncos"
  },
  {
    "pick": 109,
    "team": "KC",
    "player": "Jadon Canady",
    "position": "CB",
    "college": "Oregon",
    "team_name": "Kansas City Chiefs"
  },
  {
    "pick": 110,
    "team": "NYJ",
    "player": "Cade Klubnik",
    "position": "QB",
    "college": "Clemson",
    "team_name": "New York Jets"
  },
  {
    "pick": 111,
    "team": "DEN",
    "player": "Kage Casey",
    "position": "OT",
    "college": "Boise State",
    "team_name": "Denver Broncos"
  },
  {
    "pick": 112,
    "team": "DAL",
    "player": "Drew Shelton",
    "position": "OT",
    "college": "Penn State",
    "team_name": "Dallas Cowboys"
  },
  {
    "pick": 113,
    "team": "IND",
    "player": "Jalen Farmer",
    "position": "IOL",
    "college": "Kentucky",
    "team_name": "Indianapolis Colts"
  },
  {
    "pick": 114,
    "team": "DAL",
    "player": "Devin Moore",
    "position": "CB",
    "college": "Florida",
    "team_name": "Dallas Cowboys"
  },
  {
    "pick": 115,
    "team": "BAL",
    "player": "Elijah Sarratt",
    "position": "WR",
    "college": "Indiana",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 116,
    "team": "TB",
    "player": "Keionte Scott",
    "position": "CB",
    "college": "Miami",
    "team_name": "Tampa Bay Buccaneers"
  },
  {
    "pick": 117,
    "team": "LAC",
    "player": "Travis Burke",
    "position": "OT",
    "college": "Memphis",
    "team_name": "Los Angeles Chargers"
  },
  {
    "pick": 118,
    "team": "DET",
    "player": "Jimmy Rolder",
    "position": "LB",
    "college": "Michigan",
    "team_name": "Detroit Lions"
  },
  {
    "pick": 119,
    "team": "JAX",
    "player": "Wesley Williams",
    "position": "EDGE",
    "college": "Duke",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 120,
    "team": "GB",
    "player": "Dani Dennis-Sutton",
    "position": "EDGE",
    "college": "Penn State",
    "team_name": "Green Bay Packers"
  },
  {
    "pick": 121,
    "team": "PIT",
    "player": "Kaden Wetjen",
    "position": "WR",
    "college": "Iowa",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 122,
    "team": "LV",
    "player": "Mike Washington Jr.",
    "position": "RB",
    "college": "Arkansas",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 123,
    "team": "HOU",
    "player": "Wade Woodaz",
    "position": "LB",
    "college": "Clemson",
    "team_name": "Houston Texans"
  },
  {
    "pick": 124,
    "team": "CHI",
    "player": "Malik Muhammad",
    "position": "CB",
    "college": "Texas",
    "team_name": "Chicago Bears"
  },
  {
    "pick": 125,
    "team": "BUF",
    "player": "Skyler Bell",
    "position": "WR",
    "college": "UConn",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 126,
    "team": "BUF",
    "player": "Kaleb Elarms-Orr",
    "position": "LB",
    "college": "TCU",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 127,
    "team": "SF",
    "player": "Carver Willis",
    "position": "OT/IOL",
    "college": "Washington",
    "team_name": "San Francisco 49ers"
  },
  {
    "pick": 128,
    "team": "CIN",
    "player": "Connor Lew",
    "position": "IOL",
    "college": "Auburn",
    "team_name": "Cincinnati Bengals"
  },
  {
    "pick": 129,
    "team": "CAR",
    "player": "Will Lee III",
    "position": "CB",
    "college": "Texas A&M",
    "team_name": "Carolina Panthers"
  },
  {
    "pick": 130,
    "team": "MIA",
    "player": "Trey Moore",
    "position": "EDGE/LB",
    "college": "Texas",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 131,
    "team": "LAC",
    "player": "Genesis Smith",
    "position": "S",
    "college": "Arizona",
    "team_name": "Los Angeles Chargers"
  },
  {
    "pick": 132,
    "team": "NO",
    "player": "Jeremiah Wright",
    "position": "IOL",
    "college": "Auburn",
    "team_name": "New Orleans Saints"
  },
  {
    "pick": 133,
    "team": "BAL",
    "player": "Matthew Hibner",
    "position": "TE",
    "college": "SMU",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 134,
    "team": "ATL",
    "player": "Kendal Daniels",
    "position": "LB",
    "college": "Oklahoma",
    "team_name": "Atlanta Falcons"
  },
  {
    "pick": 135,
    "team": "IND",
    "player": "Bryce Boettcher",
    "position": "LB",
    "college": "Oregon",
    "team_name": "Indianapolis Colts"
  },
  {
    "pick": 136,
    "team": "NO",
    "player": "Bryce Lance",
    "position": "WR",
    "college": "North Dakota State",
    "team_name": "New Orleans Saints"
  },
  {
    "pick": 137,
    "team": "DAL",
    "player": "LT Overton",
    "position": "EDGE",
    "college": "Alabama",
    "team_name": "Dallas Cowboys"
  },
  {
    "pick": 138,
    "team": "MIA",
    "player": "Kyle Louis",
    "position": "LB",
    "college": "Pittsburgh",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 139,
    "team": "SF",
    "player": "Ephesians Prysock",
    "position": "CB",
    "college": "Washington",
    "team_name": "San Francisco 49ers"
  },
  {
    "pick": 140,
    "team": "CIN",
    "player": "Colbie Young",
    "position": "WR",
    "college": "Georgia",
    "team_name": "Cincinnati Bengals"
  },
  {
    "pick": 141,
    "team": "HOU",
    "player": "Kamari Ramsey",
    "position": "S",
    "college": "USC",
    "team_name": "Houston Texans"
  },
  {
    "pick": 142,
    "team": "TEN",
    "player": "Fernando Carmona Jr.",
    "position": "OT/IOL",
    "college": "Arkansas",
    "team_name": "Tennessee Titans"
  },
  {
    "pick": 143,
    "team": "ARI",
    "player": "Reggie Virgil",
    "position": "WR",
    "college": "Texas Tech",
    "team_name": "Arizona Cardinals"
  },
  {
    "pick": 144,
    "team": "CAR",
    "player": "Sam Hecht",
    "position": "IOL",
    "college": "Kansas State",
    "team_name": "Carolina Panthers"
  },
  {
    "pick": 145,
    "team": "LAC",
    "player": "Nick Barrett",
    "position": "DL",
    "college": "South Carolina",
    "team_name": "Los Angeles Chargers"
  },
  {
    "pick": 146,
    "team": "CLE",
    "player": "Parker Brailsford",
    "position": "IOL",
    "college": "Alabama",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 147,
    "team": "WSH",
    "player": "Joshua Josephs",
    "position": "EDGE",
    "college": "Tennessee",
    "team_name": "WSH"
  },
  {
    "pick": 148,
    "team": "SEA",
    "player": "Beau Stephens",
    "position": "IOL",
    "college": "Iowa",
    "team_name": "Seattle Seahawks"
  },
  {
    "pick": 149,
    "team": "CLE",
    "player": "Justin Jefferson",
    "position": "LB",
    "college": "Alabama",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 150,
    "team": "LV",
    "player": "Dalton Johnson",
    "position": "S",
    "college": "Arizona",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 151,
    "team": "CAR",
    "player": "Zakee Wheatley",
    "position": "S",
    "college": "Penn State",
    "team_name": "Carolina Panthers"
  },
  {
    "pick": 152,
    "team": "DEN",
    "player": "Justin Joly",
    "position": "TE",
    "college": "NC State",
    "team_name": "Denver Broncos"
  },
  {
    "pick": 153,
    "team": "GB",
    "player": "Jager Burton",
    "position": "IOL",
    "college": "Kentucky",
    "team_name": "Green Bay Packers"
  },
  {
    "pick": 154,
    "team": "SF",
    "player": "Jaden Dugger",
    "position": "LB",
    "college": "Louisiana",
    "team_name": "San Francisco 49ers"
  },
  {
    "pick": 155,
    "team": "TB",
    "player": "DeMonte Capehart",
    "position": "DL",
    "college": "Clemson",
    "team_name": "Tampa Bay Buccaneers"
  },
  {
    "pick": 156,
    "team": "IND",
    "player": "George Gumbs Jr.",
    "position": "EDGE",
    "college": "Florida",
    "team_name": "Indianapolis Colts"
  },
  {
    "pick": 157,
    "team": "DET",
    "player": "Keith Abney II",
    "position": "CB",
    "college": "Arizona State",
    "team_name": "Detroit Lions"
  },
  {
    "pick": 158,
    "team": "MIA",
    "player": "Michael Taaffe",
    "position": "S",
    "college": "Texas",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 159,
    "team": "MIN",
    "player": "Max Bredeson",
    "position": "FB",
    "college": "Michigan",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 160,
    "team": "TB",
    "player": "Billy Schrauth",
    "position": "IOL",
    "college": "Notre Dame",
    "team_name": "Tampa Bay Buccaneers"
  },
  {
    "pick": 161,
    "team": "KC",
    "player": "Emmett Johnson",
    "position": "RB",
    "college": "Nebraska",
    "team_name": "Kansas City Chiefs"
  },
  {
    "pick": 162,
    "team": "BAL",
    "player": "Chandler Rivers",
    "position": "CB",
    "college": "Duke",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 163,
    "team": "MIN",
    "player": "Charles Demmings",
    "position": "CB",
    "college": "Stephen F. Austin",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 164,
    "team": "JAX",
    "player": "Tanner Koziol",
    "position": "TE",
    "college": "Houston",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 165,
    "team": "TEN",
    "player": "Nicholas Singleton",
    "position": "RB",
    "college": "Penn State",
    "team_name": "Tennessee Titans"
  },
  {
    "pick": 166,
    "team": "CHI",
    "player": "Keyshaun Elliott",
    "position": "LB",
    "college": "Arizona State",
    "team_name": "Chicago Bears"
  },
  {
    "pick": 167,
    "team": "BUF",
    "player": "Jalon Kilgore",
    "position": "S",
    "college": "South Carolina",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 168,
    "team": "DET",
    "player": "Kendrick Law",
    "position": "WR",
    "college": "Kentucky",
    "team_name": "Detroit Lions"
  },
  {
    "pick": 169,
    "team": "PIT",
    "player": "Riley Nowakowski",
    "position": "TE",
    "college": "Indiana",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 170,
    "team": "CLE",
    "player": "Joe Royer",
    "position": "TE",
    "college": "Cincinnati",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 171,
    "team": "NE",
    "player": "Karon Prunty",
    "position": "CB",
    "college": "Wake Forest",
    "team_name": "New England Patriots"
  },
  {
    "pick": 172,
    "team": "NO",
    "player": "Lorenzo Styles Jr.",
    "position": "CB",
    "college": "Ohio State",
    "team_name": "New Orleans Saints"
  },
  {
    "pick": 173,
    "team": "BAL",
    "player": "Josh Cuevas",
    "position": "TE",
    "college": "Alabama",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 174,
    "team": "BAL",
    "player": "Adam Randall",
    "position": "RB",
    "college": "Clemson",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 175,
    "team": "LV",
    "player": "Hezekiah Masses",
    "position": "CB",
    "college": "California",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 176,
    "team": "KC",
    "player": "Cyrus Allen",
    "position": "WR",
    "college": "Cincinnati",
    "team_name": "Kansas City Chiefs"
  },
  {
    "pick": 177,
    "team": "MIA",
    "player": "Kevin Coleman Jr.",
    "position": "WR",
    "college": "Missouri",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 178,
    "team": "PHI",
    "player": "Cole Payton",
    "position": "QB",
    "college": "North Dakota State",
    "team_name": "Philadelphia Eagles"
  },
  {
    "pick": 179,
    "team": "SF",
    "player": "Enrique Cruz Jr.",
    "position": "OT",
    "college": "Kansas",
    "team_name": "San Francisco 49ers"
  },
  {
    "pick": 180,
    "team": "MIA",
    "player": "Seydou Traore",
    "position": "TE",
    "college": "Mississippi State",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 181,
    "team": "BUF",
    "player": "Zane Durant",
    "position": "DL",
    "college": "Penn State",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 182,
    "team": "CLE",
    "player": "Taylen Green",
    "position": "QB",
    "college": "Arkansas",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 183,
    "team": "ARI",
    "player": "Karson Sharar",
    "position": "LB",
    "college": "Iowa",
    "team_name": "Arizona Cardinals"
  },
  {
    "pick": 184,
    "team": "TEN",
    "player": "Jackie Marshall",
    "position": "DL",
    "college": "Baylor",
    "team_name": "Tennessee Titans"
  },
  {
    "pick": 185,
    "team": "TB",
    "player": "Bauer Sharp",
    "position": "TE",
    "college": "LSU",
    "team_name": "Tampa Bay Buccaneers"
  },
  {
    "pick": 186,
    "team": "NYG",
    "player": "Bobby Jamison-Travis",
    "position": "DL",
    "college": "Auburn",
    "team_name": "New York Giants"
  },
  {
    "pick": 187,
    "team": "WSH",
    "player": "Kaytron Allen",
    "position": "RB",
    "college": "Penn State",
    "team_name": "WSH"
  },
  {
    "pick": 188,
    "team": "NYJ",
    "player": "Anez Cooper",
    "position": "IOL",
    "college": "Miami",
    "team_name": "New York Jets"
  },
  {
    "pick": 189,
    "team": "CIN",
    "player": "Brian Parker II",
    "position": "IOL",
    "college": "Duke",
    "team_name": "Cincinnati Bengals"
  },
  {
    "pick": 190,
    "team": "NO",
    "player": "Barion Brown",
    "position": "WR",
    "college": "LSU",
    "team_name": "New Orleans Saints"
  },
  {
    "pick": 191,
    "team": "JAX",
    "player": "Josh Cameron",
    "position": "WR",
    "college": "Baylor",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 192,
    "team": "NYG",
    "player": "J.C. Davis",
    "position": "OT",
    "college": "Illinois",
    "team_name": "New York Giants"
  },
  {
    "pick": 193,
    "team": "NYG",
    "player": "Jack Kelly",
    "position": "LB",
    "college": "BYU",
    "team_name": "New York Giants"
  },
  {
    "pick": 194,
    "team": "TEN",
    "player": "Pat Coogan",
    "position": "IOL",
    "college": "Indiana",
    "team_name": "Tennessee Titans"
  },
  {
    "pick": 195,
    "team": "LV",
    "player": "Malik Benson",
    "position": "WR",
    "college": "Oregon",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 196,
    "team": "NE",
    "player": "Dametrious Crownover",
    "position": "OT",
    "college": "Texas A&M",
    "team_name": "New England Patriots"
  },
  {
    "pick": 197,
    "team": "LAR",
    "player": "CJ Daniels",
    "position": "WR",
    "college": "Miami",
    "team_name": "Los Angeles Rams"
  },
  {
    "pick": 198,
    "team": "MIN",
    "player": "Demond Claiborne",
    "position": "RB",
    "college": "Wake Forest",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 199,
    "team": "SEA",
    "player": "Emmanuel Henderson Jr.",
    "position": "WR",
    "college": "Kansas",
    "team_name": "Seattle Seahawks"
  },
  {
    "pick": 200,
    "team": "MIA",
    "player": "DJ Campbell",
    "position": "IOL",
    "college": "Texas",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 201,
    "team": "GB",
    "player": "Domani Jackson",
    "position": "CB",
    "college": "Alabama",
    "team_name": "Green Bay Packers"
  },
  {
    "pick": 202,
    "team": "LAC",
    "player": "Logan Taylor",
    "position": "IOL",
    "college": "Boston College",
    "team_name": "Los Angeles Chargers"
  },
  {
    "pick": 203,
    "team": "JAX",
    "player": "CJ Williams",
    "position": "WR",
    "college": "Stanford",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 204,
    "team": "HOU",
    "player": "Lewis Bond",
    "position": "WR",
    "college": "Boston College",
    "team_name": "Houston Texans"
  },
  {
    "pick": 205,
    "team": "DET",
    "player": "Skyler Gill-Howard",
    "position": "DL",
    "college": "Texas Tech",
    "team_name": "Detroit Lions"
  },
  {
    "pick": 206,
    "team": "LAC",
    "player": "Alex Harkey",
    "position": "OT",
    "college": "Oregon",
    "team_name": "Los Angeles Chargers"
  },
  {
    "pick": 207,
    "team": "PHI",
    "player": "Micah Morris",
    "position": "IOL",
    "college": "Georgia",
    "team_name": "Philadelphia Eagles"
  },
  {
    "pick": 208,
    "team": "LV",
    "player": "Anterio Thompson",
    "position": "DL",
    "college": "Washington",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 209,
    "team": "WSH",
    "player": "Matt Gulbin",
    "position": "IOL",
    "college": "Michigan State",
    "team_name": "WSH"
  },
  {
    "pick": 210,
    "team": "PIT",
    "player": "Gabriel Rubio",
    "position": "DL",
    "college": "Notre Dame",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 211,
    "team": "BAL",
    "player": "Ryan Eckley",
    "position": "P",
    "college": "Michigan State",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 212,
    "team": "NE",
    "player": "Namdi Obiazor",
    "position": "LB",
    "college": "TCU",
    "team_name": "New England Patriots"
  },
  {
    "pick": 213,
    "team": "CHI",
    "player": "Jordan van den Berg",
    "position": "DL",
    "college": "Georgia Tech",
    "team_name": "Chicago Bears"
  },
  {
    "pick": 214,
    "team": "IND",
    "player": "Caden Curry",
    "position": "EDGE",
    "college": "Ohio State",
    "team_name": "Indianapolis Colts"
  },
  {
    "pick": 215,
    "team": "ATL",
    "player": "Harold Perkins Jr.",
    "position": "LB",
    "college": "LSU",
    "team_name": "Atlanta Falcons"
  },
  {
    "pick": 216,
    "team": "GB",
    "player": "Trey Smack",
    "position": "K",
    "college": "Florida",
    "team_name": "Green Bay Packers"
  },
  {
    "pick": 217,
    "team": "ARI",
    "player": "Jayden Williams",
    "position": "OT",
    "college": "Ole Miss",
    "team_name": "Arizona Cardinals"
  },
  {
    "pick": 218,
    "team": "DAL",
    "player": "Anthony Smith (ECU)",
    "position": "WR",
    "college": "East Carolina",
    "team_name": "Dallas Cowboys"
  },
  {
    "pick": 219,
    "team": "NO",
    "player": "TJ Hall",
    "position": "CB",
    "college": "Iowa",
    "team_name": "New Orleans Saints"
  },
  {
    "pick": 220,
    "team": "BUF",
    "player": "Toriano Pride Jr.",
    "position": "CB",
    "college": "Missouri",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 221,
    "team": "CIN",
    "player": "Jack Endries",
    "position": "TE",
    "college": "Texas",
    "team_name": "Cincinnati Bengals"
  },
  {
    "pick": 222,
    "team": "DET",
    "player": "Tyre West",
    "position": "EDGE",
    "college": "Tennessee",
    "team_name": "Detroit Lions"
  },
  {
    "pick": 223,
    "team": "WSH",
    "player": "Athan Kaliakmanis",
    "position": "QB",
    "college": "Rutgers",
    "team_name": "WSH"
  },
  {
    "pick": 224,
    "team": "PIT",
    "player": "Robert Spears-Jennings",
    "position": "S",
    "college": "Oklahoma",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 225,
    "team": "TEN",
    "player": "Jaren Kanak",
    "position": "TE",
    "college": "Oklahoma",
    "team_name": "Tennessee Titans"
  },
  {
    "pick": 226,
    "team": "CIN",
    "player": "Landon Robinson",
    "position": "DL",
    "college": "Navy",
    "team_name": "Cincinnati Bengals"
  },
  {
    "pick": 227,
    "team": "CAR",
    "player": "Jackson Kuwatch",
    "position": "LB",
    "college": "Miami (Ohio)",
    "team_name": "Carolina Panthers"
  },
  {
    "pick": 228,
    "team": "NYJ",
    "player": "VJ Payne",
    "position": "S",
    "college": "Kansas State",
    "team_name": "New York Jets"
  },
  {
    "pick": 229,
    "team": "LV",
    "player": "Brandon Cleveland",
    "position": "DL",
    "college": "NC State",
    "team_name": "Las Vegas Raiders"
  },
  {
    "pick": 230,
    "team": "PIT",
    "player": "Eli Heidenreich",
    "position": "RB",
    "college": "Navy",
    "team_name": "Pittsburgh Steelers"
  },
  {
    "pick": 231,
    "team": "ATL",
    "player": "Ethan Onianwa",
    "position": "OT",
    "college": "Ohio State",
    "team_name": "Atlanta Falcons"
  },
  {
    "pick": 232,
    "team": "LAR",
    "player": "Tim Keenan III",
    "position": "DL",
    "college": "Alabama",
    "team_name": "Los Angeles Rams"
  },
  {
    "pick": 233,
    "team": "JAX",
    "player": "Zach Durfee",
    "position": "EDGE",
    "college": "Washington",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 234,
    "team": "NE",
    "player": "Behren Morton",
    "position": "QB",
    "college": "Texas Tech",
    "team_name": "New England Patriots"
  },
  {
    "pick": 235,
    "team": "MIN",
    "player": "Gavin Gerhardt",
    "position": "IOL",
    "college": "Cincinnati",
    "team_name": "Minnesota Vikings"
  },
  {
    "pick": 236,
    "team": "SEA",
    "player": "Andre Fuller",
    "position": "CB",
    "college": "Toledo",
    "team_name": "Seattle Seahawks"
  },
  {
    "pick": 237,
    "team": "IND",
    "player": "Seth McGowan",
    "position": "RB",
    "college": "Kentucky",
    "team_name": "Indianapolis Colts"
  },
  {
    "pick": 238,
    "team": "MIA",
    "player": "Max Llewellyn",
    "position": "EDGE",
    "college": "Iowa",
    "team_name": "Miami Dolphins"
  },
  {
    "pick": 239,
    "team": "BUF",
    "player": "Tommy Doman",
    "position": "P",
    "college": "Florida",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 240,
    "team": "JAX",
    "player": "Parker Hughes",
    "position": "LB",
    "college": "Middle Tennessee",
    "team_name": "Jacksonville Jaguars"
  },
  {
    "pick": 241,
    "team": "BUF",
    "player": "Ar'maj Reed-Adams",
    "position": "IOL",
    "college": "Texas A&M",
    "team_name": "Buffalo Bills"
  },
  {
    "pick": 242,
    "team": "SEA",
    "player": "Deven Eastern",
    "position": "DL",
    "college": "Minnesota",
    "team_name": "Seattle Seahawks"
  },
  {
    "pick": 243,
    "team": "HOU",
    "player": "Aiden Fisher",
    "position": "LB",
    "college": "Indiana",
    "team_name": "Houston Texans"
  },
  {
    "pick": 244,
    "team": "PHI",
    "player": "Cole Wisniewski",
    "position": "S",
    "college": "Texas Tech",
    "team_name": "Philadelphia Eagles"
  },
  {
    "pick": 245,
    "team": "NE",
    "player": "Jam Miller",
    "position": "RB",
    "college": "Alabama",
    "team_name": "New England Patriots"
  },
  {
    "pick": 246,
    "team": "DEN",
    "player": "Miles Scott",
    "position": "S",
    "college": "Illinois",
    "team_name": "Denver Broncos"
  },
  {
    "pick": 247,
    "team": "NE",
    "player": "Quintayvious Hutchins",
    "position": "EDGE",
    "college": "Boston College",
    "team_name": "New England Patriots"
  },
  {
    "pick": 248,
    "team": "CLE",
    "player": "Carsen Ryan",
    "position": "TE",
    "college": "BYU",
    "team_name": "Cleveland Browns"
  },
  {
    "pick": 249,
    "team": "KC",
    "player": "Garrett Nussmeier",
    "position": "QB",
    "college": "LSU",
    "team_name": "Kansas City Chiefs"
  },
  {
    "pick": 250,
    "team": "BAL",
    "player": "Rayshaun Benny",
    "position": "DL",
    "college": "Michigan",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 251,
    "team": "PHI",
    "player": "Uar Bernard",
    "position": "DL",
    "college": "Nigeria",
    "team_name": "Philadelphia Eagles"
  },
  {
    "pick": 252,
    "team": "PHI",
    "player": "Keyshawn James-Newby",
    "position": "EDGE",
    "college": "New Mexico",
    "team_name": "Philadelphia Eagles"
  },
  {
    "pick": 253,
    "team": "BAL",
    "player": "Evan Beerntsen",
    "position": "IOL",
    "college": "Northwestern",
    "team_name": "Baltimore Ravens"
  },
  {
    "pick": 254,
    "team": "IND",
    "player": "Deion Burks",
    "position": "WR",
    "college": "Oklahoma",
    "team_name": "Indianapolis Colts"
  },
  {
    "pick": 255,
    "team": "SEA",
    "player": "Michael Dansby",
    "position": "CB",
    "college": "Arizona",
    "team_name": "Seattle Seahawks"
  },
  {
    "pick": 256,
    "team": "DEN",
    "player": "Dallen Bentley",
    "position": "TE",
    "college": "Utah",
    "team_name": "Denver Broncos"
  },
  {
    "pick": 257,
    "team": "DEN",
    "player": "Red Murdock",
    "position": "LB",
    "college": "Buffalo",
    "team_name": "Denver Broncos"
  }
];

const draftPicksByNumber = new Map(draftPicks.map((pick) => [Number(pick.pick), pick]));

function enrichDraftPicks() {
  for (const li of document.querySelectorAll('.team .picks li')) {
    if (li.querySelector('.pick-player') || li.textContent.includes('—')) continue;

    const valueSpan = li.querySelector('.pick-val');
    const text = li.textContent || '';
    const match = text.match(/Pick\s*(\d+)/i);
    if (!match) continue;

    const pickNumber = Number(match[1]);
    const draftPick = draftPicksByNumber.get(pickNumber);
    if (!draftPick) continue;

    const playerSpan = document.createElement('span');
    playerSpan.className = 'pick-player';
    playerSpan.textContent = ' — ' + draftPick.player;

    const detailText = draftPick.position
      ? ' (' + draftPick.position + (draftPick.college ? ', ' + draftPick.college : '') + ')'
      : '';
    const detailSpan = document.createElement('span');
    detailSpan.className = 'pick-detail';
    detailSpan.textContent = detailText;

    if (valueSpan) {
      li.insertBefore(playerSpan, valueSpan);
      if (detailText) li.insertBefore(detailSpan, valueSpan);
    } else {
      li.appendChild(playerSpan);
      if (detailText) li.appendChild(detailSpan);
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', enrichDraftPicks);
} else {
  enrichDraftPicks();
}
